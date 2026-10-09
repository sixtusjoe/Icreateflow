"""Outreach API — campaigns, targets, sending accounts, templates, controls.

Mounted from main.py:

    from routers import outreach as outreach_router
    app.include_router(outreach_router.build_router(get_current_user, admin_required))

The auth dependencies are injected rather than imported so this module
never imports main.py (which imports it). Tests build the router with a
stub user for the same reason.

Two rules hold everywhere in this file:

* **Ownership is checked before anything else.** `_own_campaign` /
  `_own_account` 404 on someone else's row and 403 on an unauthorised
  action; admins see everything. No endpoint takes a user id from the
  request body.
* **Session material never leaves the process.** `_account_public()` is
  the only shape a sending account is serialized in, and it drops
  `session_state_encrypted` entirely — the API can say *whether* a session
  exists, never what it contains.
"""
from __future__ import annotations

import csv
import re
import io
import asyncio
import socket
import json
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import text

import database as db
from services.outreach import accounts as account_mgr
from services.outreach import config as cfg
from services.outreach import (
    attachments,
    discovery,
    importer,
    proxies,
    session_capture,
    session_viewer,
    watch_run,
)
from services.outreach import companion
from services.outreach import runner as outreach_runner
from services.outreach import comments
from services.outreach import queue as job_queue
from services.outreach import stats
from services.outreach import templates as template_svc
from services.outreach.browser import DRIVERS
from services.outreach.constants import (
    TARGET_STATUSES,
    ACTIVITY_COMMENT,
    ACTIVITY_FOLLOW,
    ACTIVITY_UNFOLLOW,
    JOB_FAILED,
    JOB_SUCCEEDED,
    RESULT_FOLLOW_REQUESTED,
    RESULT_SENT,
    ACTIVITY_MESSAGE,
    CAMPAIGN_ACTIVITIES,
    UNFOLLOW_PLATFORMS,
    ACCOUNT_IDLE,
    ACCOUNT_PURPOSE_SENDING,
    ACCOUNT_PURPOSES,
    ACCOUNT_VIAS,
    ACCOUNT_VIA_BROWSER,
    ACCOUNT_VIA_PHONE,
    PHONE_PLATFORMS,
    ACCOUNT_PAUSED,
    AUDIT_ACCOUNT_ASSIGNED,
    AUDIT_ACCOUNT_CREATED,
    AUDIT_ACCOUNT_DELETED,
    AUDIT_ACCOUNT_DISABLED,
    AUDIT_ACCOUNT_ENABLED,
    AUDIT_ACCOUNT_SESSION_SET,
    AUDIT_ACCOUNT_UNASSIGNED,
    AUDIT_ACCOUNT_UPDATED,
    AUDIT_CAMPAIGN_CREATED,
    AUDIT_CAMPAIGN_DELETED,
    AUDIT_CAMPAIGN_PAUSED,
    AUDIT_CAMPAIGN_RESUMED,
    AUDIT_CAMPAIGN_RETRY_FAILED,
    AUDIT_CAMPAIGN_STARTED,
    AUDIT_CAMPAIGN_STOPPED,
    AUDIT_TARGETS_IMPORTED,
    AUDIT_WORKERS_TOGGLED,
    CAMPAIGN_DRAFT,
    CAMPAIGN_PAUSED,
    CAMPAIGN_RUNNING,
)
from services.outreach.crypto import (
    SessionCryptoUnavailable,
    crypto_available,
    decrypt_session,
    encrypt_session,
)

MAX_IMPORT_BYTES = importer.MAX_BYTES


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------

class CampaignCreate(BaseModel):
    name: str
    description: Optional[str] = None
    message_template: Optional[str] = None
    template_id: Optional[int] = None
    template_vars: Optional[dict[str, Any]] = None
    platform: str = "tiktok"
    #: "message" (default), "follow" or "comment".
    activity: str = ACTIVITY_MESSAGE
    #: Comment campaigns: the video, how many comments, and the lines to
    #: draw from. Ignored by the other two.
    target_url: Optional[str] = None
    comment_count: Optional[int] = None
    comment_variations: Optional[list[str]] = None
    max_jobs: Optional[int] = None
    max_jobs_per_account: Optional[int] = None
    retry_limit: Optional[int] = None


def _dump_variations(lines: Optional[list[str]]) -> Optional[str]:
    """Comment lines, as the column stores them.

    None means "not given" and leaves what is there; an empty list is a
    deliberate clear. Blank lines are dropped so an editor's trailing
    newline does not become a comment that posts nothing.
    """
    if lines is None:
        return None
    kept = [str(line).strip() for line in lines if str(line).strip()]
    return json.dumps(kept)


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    activity: Optional[str] = None
    description: Optional[str] = None
    message_template: Optional[str] = None
    template_id: Optional[int] = None
    template_vars: Optional[dict[str, Any]] = None
    target_url: Optional[str] = None
    comment_count: Optional[int] = None
    comment_variations: Optional[list[str]] = None
    max_jobs: Optional[int] = None
    max_jobs_per_account: Optional[int] = None
    retry_limit: Optional[int] = None


class TargetsPaste(BaseModel):
    content: str


class AccountCreate(BaseModel):
    name: str
    platform: str = "tiktok"
    #: "sending" or "discovery". Kept apart so harvesting cannot cost the
    #: account that sends.
    purpose: str = ACCOUNT_PURPOSE_SENDING
    session_reference: Optional[str] = None


class AccountUpdate(BaseModel):
    #: An outbound proxy for this account, as scheme://user:pass@host:port.
    #: Blank clears it. Stored encrypted and never returned.
    proxy_url: Optional[str] = None
    name: Optional[str] = None
    enabled: Optional[bool] = None
    purpose: Optional[str] = None
    session_reference: Optional[str] = None
    #: The phone (adb serial) that does this account's TikTok follows, and
    #: the handle the app on it must be signed in as. Blank clears.
    device_serial: Optional[str] = None
    device_handle: Optional[str] = None
    #: "browser" or "phone" — whether the server's browser or the user's
    #: phone app does this account's work. Switching to phone needs a
    #: handle, here or already stored.
    via: Optional[str] = None


class LeadSearchCreate(BaseModel):
    """What to look for. The model turns this into queries.

    `seed_accounts` short-circuits all of that: naming accounts means
    harvesting their followers instead, since the operator has already said
    exactly whose audience they want.
    """

    niche: str = ""
    seed_accounts: Optional[str] = None
    location: Optional[str] = None
    interests: Optional[str] = None
    wanted: int = 50
    platform: str = "instagram"
    account_id: Optional[int] = None
    #: Commenters are already on the post the author came from, so they
    #: cost nothing extra. Likers live behind their own URL — one more page
    #: load per post. Both find people who engaged rather than merely
    #: posted, which is usually the better list.
    include_commenters: bool = False
    include_likers: bool = False
    include_replies: bool = True
    #: Open each profile for its bio and follower count. One page load per
    #: lead, so off unless asked for.
    enrich_profiles: bool = False


class LeadImport(BaseModel):
    lead_ids: list[int]
    #: Split the chosen leads across these campaigns instead of putting
    #: them all in the one the finder was opened from. Empty means the one.
    campaign_ids: Optional[list[int]] = None


class AccountSession(BaseModel):
    #: Playwright storage_state JSON, as a string or an object.
    session_state: Any
    session_reference: Optional[str] = None


class TemplateCreate(BaseModel):
    name: str
    body: str
    defaults: Optional[dict[str, Any]] = None


class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    body: Optional[str] = None
    defaults: Optional[dict[str, Any]] = None


class TemplatePreview(BaseModel):
    body: str
    variables: Optional[dict[str, Any]] = None


class SettingsUpdate(BaseModel):
    values: dict[str, Any]


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def _tag_utc(row: dict) -> dict:
    """Tag naive UTC timestamps so the browser parses them as UTC.

    Same helper as main.py's `_tag_utc` — duplicated rather than imported
    to keep this module free of a main.py import.
    """
    out = dict(row)
    for key, value in list(out.items()):
        if isinstance(value, datetime) and value.tzinfo is None:
            out[key] = value.replace(tzinfo=timezone.utc)
    return out


#: Columns that must never reach a client.
_ACCOUNT_SECRET_FIELDS = ("session_state_encrypted",
    "proxy_url_encrypted",
)


def _account_public(row: dict) -> dict:
    """The only serialization of a sending account.

    Drops the encrypted session and replaces it with a boolean — the
    dashboard needs to know an account *has* a session, never what it is.
    """
    out = _tag_utc(row)
    has_session = bool(out.get("session_state_encrypted"))
    for field in _ACCOUNT_SECRET_FIELDS:
        out.pop(field, None)
    out["has_session"] = has_session
    # The host, never the password — enough for the page to show which
    # address an account goes out through.
    stored = row.get("proxy_url_encrypted")
    if not stored:
        out["proxy"] = None
    else:
        try:
            proxy = proxies.parse(decrypt_session(stored))
            out["proxy"] = proxy.safe if proxy else None
        except (proxies.ProxyInvalid, SessionCryptoUnavailable, ValueError):
            # A stored value that cannot be read is worth showing as such;
            # anything else is a bug and should not be swallowed here.
            out["proxy"] = "(unreadable)"
    return out


def _template_public(row: dict) -> dict:
    """A template as the client sees it — never its attachment's path."""
    out = _tag_utc(row)
    out["variables"] = template_svc.extract_variables(row.get("body") or "")
    out["has_attachment"] = bool(out.pop("attachment_path", None))
    # Stored as JSON, handed over as a list — the client should not have to
    # know which of those it is getting.
    raw = out.get("comment_variations")
    if isinstance(raw, str):
        try:
            loaded = json.loads(raw)
        except ValueError:
            loaded = None
        out["comment_variations"] = loaded if isinstance(loaded, list) else []
    elif raw is None:
        out["comment_variations"] = []
    return out


def _remaining_phrase(until) -> str:
    """"12m", "3h 5m", or "no time" — for an audit line, not a UI."""
    if not isinstance(until, datetime):
        return "no time"
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    left = int((until - datetime.now(timezone.utc)).total_seconds())
    if left <= 0:
        return "no time"
    hours, minutes = divmod(left // 60, 60)
    return f"{hours}h {minutes}m" if hours else f"{minutes}m"


def _campaign_public(row: dict) -> dict:
    out = _tag_utc(row)
    total = int(out.get("total_targets") or 0)
    processed = int(out.get("processed_count") or 0)
    out["progress"] = round(processed / total, 4) if total else 0.0
    # The attachment's location on disk is nobody's business but the
    # driver's. The client only needs to know there is one and what it was
    # called; the bytes come from the endpoint, which checks ownership.
    out["has_attachment"] = bool(out.pop("attachment_path", None))
    # Whether the platform refused the words the campaign has *now*. False
    # once the message is edited, which is what the page's "change the
    # message" prompt waits for.
    refused = out.pop("refused_template", None)
    out["message_refused"] = bool(refused) and refused == (out.get("message_template") or "")
    # The platform is refusing the sending account itself, whatever it says.
    out["account_refused"] = bool(out.pop("refused_account_id", None))
    # Stored as JSON, handed over as a list — the client should not have to
    # know which of those it is getting, and a string arriving where a list
    # is expected crashes the page that renders it.
    raw = out.get("comment_variations")
    if isinstance(raw, str):
        try:
            loaded = json.loads(raw)
        except ValueError:
            loaded = None
        out["comment_variations"] = loaded if isinstance(loaded, list) else []
    elif not isinstance(raw, list):
        out["comment_variations"] = []
    return out


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

class CompanionLink(BaseModel):
    """The phone app linking itself to a TikTok account for follows."""
    device_id: str
    account_id: int
    handle: str


class CompanionDevice(BaseModel):
    device_id: str


class CompanionResult(BaseModel):
    """What the phone did with one follow — a status from companion.PHONE_RESULTS."""
    device_id: str
    status: str
    error: Optional[str] = None
    detail: Optional[dict] = None


def build_router(get_current_user, admin_required) -> APIRouter:
    """Build the outreach router around the app's auth dependencies."""

    router = APIRouter(prefix="/api/outreach", tags=["outreach"])

    # --- ownership helpers ------------------------------------------------

    async def _own_campaign(database, campaign_id: int, user: dict) -> dict:
        row = await db.get_outreach_campaign(database, campaign_id)
        if not row:
            raise HTTPException(404, "Campaign not found")
        campaign = dict(row)
        if user.get("role") != "admin" and campaign.get("user_id") != user["id"]:
            raise HTTPException(403, "Access denied")
        return campaign

    async def _has_worked(database, campaign_id: int) -> bool:
        """Whether any of the campaign's people has been followed, messaged or
        tried and failed. Cancelled jobs were never done, so they don't count."""
        row = (await database.session.execute(text(
            "SELECT 1 FROM outreach_jobs WHERE campaign_id = :cid "
            "   AND status IN (:succeeded, :failed) LIMIT 1"
        ), {"cid": campaign_id, "succeeded": JOB_SUCCEEDED, "failed": JOB_FAILED})).first()
        return row is not None

    async def _own_account(database, account_id: int, user: dict) -> dict:
        row = await db.get_sending_account(database, account_id)
        if not row:
            raise HTTPException(404, "Sending account not found")
        account = dict(row)
        if user.get("role") != "admin" and account.get("user_id") != user["id"]:
            raise HTTPException(403, "Access denied")
        return account

    async def _own_template(database, template_id: int, user: dict) -> dict:
        row = await db.get_outreach_template(database, template_id)
        if not row:
            raise HTTPException(404, "Template not found")
        template = dict(row)
        if user.get("role") != "admin" and template.get("user_id") != user["id"]:
            raise HTTPException(403, "Access denied")
        return template

    def _scope(user: dict) -> Optional[int]:
        """None for admins (see everything), else the caller's id."""
        return None if user.get("role") == "admin" else user["id"]

    # =====================================================================
    # Dashboard summary
    # =====================================================================

    #: What the dashboard's range control offers. Anything else is refused
    #: rather than clamped — a silently substituted window would put a
    #: figure on screen under a label that does not describe it.
    SUMMARY_WINDOWS = (7, 14, 30, 90)

    @router.get("/summary")
    async def outreach_summary(days: int = 14,
                               user: dict = Depends(get_current_user)):
        """Everything the dashboard needs about outreach, in one round trip.

        The campaign list already carries per-campaign counters, so this
        deliberately does not repeat them. What it adds is the things no
        existing endpoint can answer without fetching every row: how many
        leads discovery has found, how sends are distributed over the
        chosen window, which weekday actually sends the most, and how the
        campaigns and sending accounts divide by state. All of it is
        scoped to the caller.

        `days` selects the window for `daily_sends` and `range` only. The
        target counts, the delivery rate and the weekday histogram are
        all-time by definition and ignore it — every one of them is
        labelled as such on the dashboard.
        """
        if days not in SUMMARY_WINDOWS:
            raise HTTPException(
                400, f"days must be one of: "
                     f"{', '.join(str(d) for d in SUMMARY_WINDOWS)}")
        uid = _scope(user)
        database = await db.get_db()
        try:
            def scoped(sql: str, alias: str) -> str:
                # Admins (uid is None) see the whole instance; everyone else
                # is filtered to their own rows by the same parameter, so the
                # query shape never changes between the two.
                # The cast is load-bearing: an admin passes NULL here, and
                # Postgres cannot infer a bare parameter's type from
                # `$1 IS NULL` alone — it raises AmbiguousParameterError.
                return sql.replace(
                    "/*scope*/",
                    f"AND (CAST(:uid AS INTEGER) IS NULL "
                    f"     OR {alias}.user_id = CAST(:uid AS INTEGER))")

            async def rows(sql: str, alias: str, **params):
                cur = await database.session.execute(
                    text(scoped(sql, alias)), {"uid": uid, **params})
                return cur.all()

            states = {r[0]: int(r[1]) for r in await rows(
                "SELECT t.status, COUNT(*) FROM outreach_targets t "
                "  JOIN outreach_campaigns c ON c.id = t.campaign_id "
                " WHERE TRUE /*scope*/ GROUP BY 1", "c")}

            # Every day in the window, including the silent ones. Grouping
            # alone drops days with no sends, which left the line plotting
            # 12 points across a 14-day axis — evenly spaced, so a gap in
            # sending read as a smooth stretch rather than the hole it was.
            daily = [{"date": str(r[0]), "count": int(r[1])} for r in await rows(
                "SELECT d::date, COALESCE(x.c, 0) FROM generate_series("
                "         CURRENT_DATE - (CAST(:days AS INTEGER) - 1),"
                "         CURRENT_DATE, INTERVAL '1 day') d "
                "  LEFT JOIN (SELECT t.sent_at::date AS sd, COUNT(*) AS c "
                "               FROM outreach_targets t "
                "               JOIN outreach_campaigns c ON c.id = t.campaign_id "
                "              WHERE t.status = 'sent' AND t.sent_at IS NOT NULL "
                "                AND t.sent_at::date > CURRENT_DATE "
                "                                      - CAST(:days AS INTEGER) "
                "                /*scope*/ GROUP BY 1) x ON x.sd = d::date "
                " ORDER BY 1", "c", days=days)]

            # The same window, and the one immediately before it, so the
            # dashboard compares like with like at any range rather than
            # always pitting seven days against seven.
            def window_sent(lo: str, hi: str) -> str:
                return ("SELECT COUNT(*) FROM outreach_targets t "
                        "  JOIN outreach_campaigns c ON c.id = t.campaign_id "
                        " WHERE t.status = 'sent' AND t.sent_at IS NOT NULL "
                        f"   AND t.sent_at::date > {lo} AND t.sent_at::date <= {hi} "
                        " /*scope*/")

            n = "CAST(:days AS INTEGER)"
            range_sent = int((await rows(
                window_sent(f"CURRENT_DATE - {n}", "CURRENT_DATE"),
                "c", days=days))[0][0] or 0)
            range_prev = int((await rows(
                window_sent(f"CURRENT_DATE - 2 * {n}", f"CURRENT_DATE - {n}"),
                "c", days=days))[0][0] or 0)

            weekday = {r[0].strip(): int(r[1]) for r in await rows(
                "SELECT to_char(t.sent_at, 'Dy'), COUNT(*) FROM outreach_targets t "
                "  JOIN outreach_campaigns c ON c.id = t.campaign_id "
                " WHERE t.status = 'sent' AND t.sent_at IS NOT NULL /*scope*/ "
                " GROUP BY 1", "c")}

            leads = int((await database.session.execute(
                text(scoped(
                    "SELECT COUNT(*) FROM outreach_leads l "
                    "  JOIN outreach_lead_searches s ON s.id = l.search_id "
                    " WHERE TRUE /*scope*/", "s")), {"uid": uid})).scalar() or 0)

            accounts = {r[0]: int(r[1]) for r in await rows(
                "SELECT a.status, COUNT(*) FROM outreach_sending_accounts a "
                " WHERE TRUE /*scope*/ GROUP BY 1", "a")}

            # Campaigns by state, for the same reason the target states are
            # here: the sidebar wants one number — how many campaigns have
            # finished — and the campaign list is a far heavier call to make
            # for it. Only the states actually present appear, so a reader
            # must treat a missing key as zero.
            campaigns = {r[0]: int(r[1]) for r in await rows(
                "SELECT c.status, COUNT(*) FROM outreach_campaigns c "
                " WHERE TRUE /*scope*/ GROUP BY 1", "c")}

            # What the most recent discovery run turned up, so the dashboard
            # can say where the newest leads came from rather than only how
            # many exist in total.
            latest = (await database.session.execute(
                text(scoped(
                    "SELECT s.id, s.found, s.status FROM outreach_lead_searches s "
                    " WHERE TRUE /*scope*/ ORDER BY s.id DESC LIMIT 1", "s")),
                {"uid": uid})).first()

            sent = states.get("sent", 0)
            # Delivery rate is over what was *attempted*, so targets still
            # sitting in the queue must not count against it.
            attempted = sent + states.get("failed", 0) + states.get("skipped", 0)
            return {
                "targets": states,
                "total_targets": sum(states.values()),
                "sent": sent,
                "attempted": attempted,
                "delivery_rate": round(sent / attempted, 4) if attempted else 0.0,
                "leads": leads,
                "latest_search": ({"id": latest[0], "found": int(latest[1] or 0),
                                   "status": latest[2]} if latest else None),
                "accounts": accounts,
                "campaigns": campaigns,
                "daily_sends": daily,
                "weekday_sends": weekday,
                # The only range-scoped block on the payload. Everything
                # above it is all-time, so a caller can never mistake one
                # for the other.
                "range": {"days": days, "sent": range_sent, "prev_sent": range_prev},
            }
        finally:
            await database.close()

    # =====================================================================
    # Campaigns
    # =====================================================================

    @router.get("/campaigns")
    async def list_campaigns(user: dict = Depends(get_current_user)):
        database = await db.get_db()
        try:
            rows = await db.get_outreach_campaigns(database, user_id=_scope(user))
            return [_campaign_public(dict(r)) for r in rows]
        finally:
            await database.close()

    @router.post("/campaigns")
    async def create_campaign(data: CampaignCreate, user: dict = Depends(get_current_user)):
        name = (data.name or "").strip()
        if not name:
            raise HTTPException(400, "Campaign name is required")
        if data.platform not in importer.PLATFORMS:
            raise HTTPException(400, f"Unsupported platform: {data.platform}")
        if data.activity not in CAMPAIGN_ACTIVITIES:
            raise HTTPException(
                400, f"activity must be one of: {', '.join(CAMPAIGN_ACTIVITIES)}")
        if data.activity == ACTIVITY_UNFOLLOW and data.platform not in UNFOLLOW_PLATFORMS:
            raise HTTPException(
                400, "Unfollowing works on TikTok and Instagram only, for now")

        database = await db.get_db()
        try:
            body = data.message_template
            template = None
            if data.template_id:
                template = await _own_template(database, data.template_id, user)
                body = body or template["body"]
            # Validated now so a broken template can't reach the worker.
            # A follow campaign sends nothing, so it needs no template and
            # must not be rejected for lacking one.
            try:
                if data.activity not in (ACTIVITY_FOLLOW, ACTIVITY_UNFOLLOW,
                                         ACTIVITY_COMMENT):
                    template_svc.validate_template(
                        body or "", known_variables=(data.template_vars or {}).keys()
                    )
            except template_svc.TemplateError as exc:
                raise HTTPException(400, str(exc)) from exc

            campaign_id = await db.create_outreach_campaign(
                database,
                user_id=user["id"],
                name=name,
                description=(data.description or "").strip() or None,
                # Never None. The column is NOT NULL with a server default
                # of "", but a default only applies to a column left out of
                # the INSERT — passing NULL explicitly is a constraint
                # violation, which is a 500 rather than the empty template
                # the default was there to provide.
                #
                # A follow or comment campaign legitimately has no message,
                # and the client is right to omit the field for those. It
                # arrives here as None because that is what Pydantic fills
                # an absent optional with, so the emptiness is restored here.
                message_template=body or "",
                template_id=data.template_id,
                template_vars=template_svc.dump_vars(data.template_vars),
                platform=data.platform,
                activity=data.activity,
                target_url=(data.target_url or "").strip() or None,
                comment_count=int(data.comment_count or 0),
                comment_variations=_dump_variations(data.comment_variations),
                status=CAMPAIGN_DRAFT,
                max_jobs=data.max_jobs,
                max_jobs_per_account=data.max_jobs_per_account,
                retry_limit=data.retry_limit,
            )
            # A template's image becomes the campaign's own copy. Sharing
            # the file would mean editing a template changed what a running
            # campaign sends, without anyone touching that campaign.
            if template is not None and dict(template).get("attachment_path"):
                tpl = dict(template)
                path, att_name = attachments.copy_for_campaign(
                    tpl.get("attachment_path"), campaign_id, tpl.get("attachment_name")
                )
                if path:
                    await db.update_outreach_campaign(
                        database, campaign_id,
                        attachment_path=path, attachment_name=att_name,
                    )

            await db.log_outreach_audit(
                database, AUDIT_CAMPAIGN_CREATED, "campaign", campaign_id,
                user_id=user["id"], detail=name,
            )
            row = await db.get_outreach_campaign(database, campaign_id)
            return _campaign_public(dict(row))
        finally:
            await database.close()

    @router.get("/campaigns/{campaign_id}")
    async def get_campaign(campaign_id: int, user: dict = Depends(get_current_user)):
        """Everything the campaign detail page renders in one call."""
        database = await db.get_db()
        try:
            campaign = await _own_campaign(database, campaign_id, user)
            settings = await cfg.get_all(database)
            counts = await db.count_outreach_targets(database, campaign_id)
            jobs = await db.get_outreach_jobs(database, campaign_id=campaign_id, limit=25)
            assigned = await db.get_campaign_account_ids(database, campaign_id)
            eligible = await account_mgr.eligible_account_ids(database, campaign)
            account_rows = await db.get_sending_accounts(
                database, user_id=campaign.get("user_id"), platform=campaign.get("platform")
            )
            audit = await db.get_outreach_audit_logs(
                database, entity_type="campaign", entity_id=campaign_id, limit=25
            )
            errors = await db.get_outreach_jobs(
                database, campaign_id=campaign_id, status="failed", limit=25
            )
            return {
                "campaign": _campaign_public(campaign),
                "target_counts": counts,
                "job_counts": await job_queue.job_counts(database, campaign_id),
                "success_outcomes": await _success_outcomes(database, campaign_id),
                "recent_jobs": [_tag_utc(dict(j)) for j in jobs],
                "failed_jobs": [_tag_utc(dict(j)) for j in errors],
                "assigned_account_ids": assigned,
                "eligible_account_ids": eligible,
                "accounts": [_account_public(dict(a)) for a in account_rows],
                "audit": [_tag_utc(dict(a)) for a in audit],
                "limits": {
                    "max_jobs": cfg.campaign_limit(
                        campaign, settings, "max_jobs", "outreach_max_jobs_per_campaign"
                    ),
                    "max_jobs_per_account": cfg.campaign_limit(
                        campaign, settings, "max_jobs_per_account",
                        "outreach_max_jobs_per_account",
                    ),
                    "retry_limit": job_queue.retry_limit_for(campaign, settings),
                },
                "workers_enabled": settings[cfg.WORKERS_ENABLED_KEY],
                "driver": settings[cfg.DRIVER_KEY],
            }
        finally:
            await database.close()

    async def _success_outcomes(database, campaign_id: int) -> dict[str, int]:
        """What this campaign's successes actually were.

        `successful_count` cannot answer "are the follows landing": a
        profile already followed succeeds without anything being pressed,
        and a private one succeeds as a request that may never be accepted.
        Only `sent` moved the account's following count.
        """
        rows = (await database.session.execute(
            text(
                "SELECT COALESCE(result_status, 'unknown') AS r, COUNT(*) "
                "  FROM outreach_jobs "
                " WHERE campaign_id = :cid AND status = 'succeeded' "
                " GROUP BY 1"
            ),
            {"cid": campaign_id},
        )).all()
        return {str(r): int(n) for r, n in rows}

    async def _live_now(database, campaign: dict) -> dict[str, Any]:
        """What a running campaign is doing this second, for the page.

        `jobs`: every job being worked on, with the person, the account and
        the step its driver last reported. `next_send_at`: with nothing in
        hand, when the soonest account comes off its rest between sends —
        the gap that otherwise looks like the campaign has stalled.
        """
        rows = (await database.session.execute(
            text(
                "SELECT j.id, j.step, j.step_at, j.started_at, t.username, "
                "       a.name AS account_name, a.via AS account_via "
                "  FROM outreach_jobs j "
                "  JOIN outreach_targets t ON t.id = j.target_id "
                "  LEFT JOIN outreach_sending_accounts a ON a.id = j.sending_account_id "
                " WHERE j.campaign_id = :cid AND j.status = 'processing' "
                " ORDER BY j.started_at"
            ),
            {"cid": campaign["id"]},
        )).mappings().all()
        jobs = [_tag_utc(dict(r)) for r in rows]
        last = (await database.session.execute(
            text(
                "SELECT j.status, j.result_status, j.completed_at, t.username "
                "  FROM outreach_jobs j "
                "  JOIN outreach_targets t ON t.id = j.target_id "
                " WHERE j.campaign_id = :cid AND j.completed_at IS NOT NULL "
                " ORDER BY j.completed_at DESC LIMIT 1"
            ),
            {"cid": campaign["id"]},
        )).mappings().first()
        next_send_at = None
        if campaign.get("status") == "running" and not jobs:
            settings = await cfg.get_all(database)
            assigned = await db.get_campaign_account_ids(database, campaign["id"])
            params: dict[str, Any] = {
                "platform": campaign.get("platform") or "tiktok",
                "gap": int(settings["outreach_min_send_interval_seconds"]),
                "uid": campaign.get("user_id"),
            }
            scope = "a.user_id = :uid" if campaign.get("user_id") is not None else "TRUE"
            if assigned:
                params.update({f"a{i}": v for i, v in enumerate(assigned)})
                scope += f" AND a.id IN ({', '.join(f':a{i}' for i in range(len(assigned)))})"
            row = (await database.session.execute(
                text(
                    "SELECT MIN(a.last_activity_at) + (:gap * INTERVAL '1 second') "
                    "  FROM outreach_sending_accounts a "
                    " WHERE a.platform = :platform AND a.enabled = TRUE "
                    f"  AND a.status = 'idle' AND {scope}"
                ),
                params,
            )).first()
            due = row[0] if row else None
            if due is not None and due > datetime.now(timezone.utc).replace(tzinfo=None):
                next_send_at = _tag_utc({"t": due})["t"]
        return {"jobs": jobs, "next_send_at": next_send_at,
                "last": _tag_utc(dict(last)) if last else None}

    @router.get("/campaigns/{campaign_id}/progress")
    async def campaign_progress(campaign_id: int, user: dict = Depends(get_current_user)):
        """Small payload for the dashboard's live poll."""
        database = await db.get_db()
        try:
            campaign = await _own_campaign(database, campaign_id, user)
            counts = await db.count_outreach_targets(database, campaign_id)
            totals = stats.totals_from_counts(counts)
            jobs = await db.get_outreach_jobs(database, campaign_id=campaign_id, limit=10)
            paused = _tag_utc({"paused_until": campaign.get("paused_until")})
            return {
                "status": campaign["status"],
                **totals,
                # Carried on the poll, not just the detail load, so the
                # countdown on the page is the server's clock rather than
                # one the browser started when it happened to open.
                "paused_until": paused.get("paused_until"),
                "paused_reason": campaign.get("paused_reason"),
                "message_refused": bool(campaign.get("refused_template"))
                and campaign.get("refused_template")
                == (campaign.get("message_template") or ""),
                "account_refused": bool(campaign.get("refused_account_id")),
                "target_counts": counts,
                "success_outcomes": await _success_outcomes(database, campaign_id),
                "recent_jobs": [_tag_utc(dict(j)) for j in jobs],
                "live": await _live_now(database, campaign),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        finally:
            await database.close()

    @router.put("/campaigns/{campaign_id}")
    async def update_campaign(
        campaign_id: int, data: CampaignUpdate, user: dict = Depends(get_current_user)
    ):
        database = await db.get_db()
        try:
            campaign = await _own_campaign(database, campaign_id, user)
            updates: dict[str, Any] = {}
            for field in ("name", "description", "max_jobs", "max_jobs_per_account", "retry_limit"):
                value = getattr(data, field)
                if value is not None:
                    updates[field] = value
            if data.template_id is not None:
                await _own_template(database, data.template_id, user)
                updates["template_id"] = data.template_id
            if data.template_vars is not None:
                updates["template_vars"] = template_svc.dump_vars(data.template_vars)
            # What the campaign does, and what it sends, is frozen while it
            # runs. Editing the message was already refused; the rest was
            # not, so a running campaign could be switched from messaging
            # to following mid-flight and finish with some targets messaged
            # and some followed, and nothing recording which was which.
            # Name, description and the job limits stay editable — renaming
            # a run or throttling it down changes nothing already done.
            if campaign["status"] == CAMPAIGN_RUNNING:
                frozen = [
                    name for name in (
                        "activity", "message_template", "target_url",
                        "comment_count", "comment_variations",
                    )
                    if getattr(data, name) is not None
                ]
                if frozen:
                    raise HTTPException(
                        400,
                        "Pause the campaign before editing what it sends "
                        f"({', '.join(sorted(frozen))})",
                    )
            if data.message_template is not None:
                try:
                    template_svc.validate_template(data.message_template)
                except template_svc.TemplateError as exc:
                    raise HTTPException(400, str(exc)) from exc
                updates["message_template"] = data.message_template
            if data.activity is not None:
                if data.activity not in CAMPAIGN_ACTIVITIES:
                    raise HTTPException(
                        400,
                        f"activity must be one of: {', '.join(CAMPAIGN_ACTIVITIES)}")
                if (data.activity == ACTIVITY_UNFOLLOW
                        and (campaign.get("platform") or "tiktok") not in UNFOLLOW_PLATFORMS):
                    raise HTTPException(
                        400, "Unfollowing works on TikTok and Instagram only, for now")
                # Once anyone has been worked on, the rest of the list was
                # picked for the old activity: a follow campaign switched to
                # unfollow ran its 320 not-yet-followed people as unfollows
                # (2026-09-28) instead of undoing the 665 it had followed.
                if data.activity != campaign.get("activity") and await _has_worked(
                        database, campaign_id):
                    raise HTTPException(400, (
                        "This campaign has already worked on people, so what it does can't "
                        "change — the rest of its list would be done the new way. "
                        + ("To undo its follows, use “Unfollow everyone it followed”."
                           if data.activity == ACTIVITY_UNFOLLOW
                           else "Start a new campaign for that instead.")))
                updates["activity"] = data.activity
            if data.target_url is not None:
                updates["target_url"] = data.target_url.strip() or None
            if data.comment_count is not None:
                updates["comment_count"] = max(0, int(data.comment_count))
            if data.comment_variations is not None:
                updates["comment_variations"] = _dump_variations(
                    data.comment_variations)
            if updates:
                await db.update_outreach_campaign(database, campaign_id, **updates)
            row = await db.get_outreach_campaign(database, campaign_id)
            return _campaign_public(dict(row))
        finally:
            await database.close()

    @router.delete("/campaigns/{campaign_id}")
    async def delete_campaign(campaign_id: int, user: dict = Depends(get_current_user)):
        database = await db.get_db()
        try:
            campaign = await _own_campaign(database, campaign_id, user)
            if campaign["status"] == CAMPAIGN_RUNNING:
                raise HTTPException(400, "Stop the campaign before deleting it")
            await db.delete_outreach_campaign(database, campaign_id)
            await db.log_outreach_audit(
                database, AUDIT_CAMPAIGN_DELETED, "campaign", campaign_id,
                user_id=user["id"], detail=campaign.get("name"),
            )
            return {"ok": True}
        finally:
            await database.close()

    # --- targets ---------------------------------------------------------

    async def _do_import(database, campaign: dict, content, user: dict) -> dict:
        try:
            summary = await importer.import_targets(
                database, campaign["id"], content, campaign.get("platform") or "tiktok"
            )
        except importer.ImportError_ as exc:
            raise HTTPException(400, str(exc)) from exc
        await db.log_outreach_audit(
            database, AUDIT_TARGETS_IMPORTED, "campaign", campaign["id"],
            user_id=user["id"],
            detail=(
                f"imported={summary['imported']} ready={summary['ready']} "
                f"duplicates={summary['duplicates']} invalid={summary['invalid']}"
            ),
        )
        return summary

    @router.post("/campaigns/{campaign_id}/unfollow-followed")
    async def unfollow_followed(campaign_id: int, user: dict = Depends(get_current_user)):
        """A new unfollow campaign for everyone this follow campaign followed,
        in the order they were followed.

        Follow jobs that succeeded with `sent`, and requests it sent to
        private accounts (`follow_requested`) — accepted ones are unfollowed,
        waiting ones withdrawn. Already following is left out: that wasn't
        this campaign's follow to undo. The same accounts are
        assigned, so each person is unfollowed by the account that followed
        them (the worker holds to that either way). Created as a draft: it
        does nothing until it's started.
        """
        database = await db.get_db()
        try:
            source = await _own_campaign(database, campaign_id, user)
            if (source.get("activity") or ACTIVITY_MESSAGE) != ACTIVITY_FOLLOW:
                raise HTTPException(400, "Only a follow campaign has people to unfollow")
            platform = source.get("platform") or "tiktok"
            if platform not in UNFOLLOW_PLATFORMS:
                raise HTTPException(400, "Unfollowing works on TikTok and Instagram only")
            # In the order they were followed, the first follow first: the
            # list is imported in this order and the queue works it in list
            # order, so the oldest follows are undone first.
            rows = (await database.session.execute(text(
                "SELECT username, profile_url FROM ("
                "  SELECT DISTINCT ON (lower(t.username)) t.username, t.profile_url, "
                "         COALESCE(j.completed_at, t.sent_at, j.updated_at) AS followed_at "
                "    FROM outreach_targets t JOIN outreach_jobs j ON j.target_id = t.id "
                "   WHERE t.campaign_id = :cid AND j.status = :succeeded "
                "     AND j.result_status IN (:sent, :requested) "
                "   ORDER BY lower(t.username), followed_at"
                ") followed ORDER BY followed_at, username"
            ), {"cid": campaign_id, "succeeded": JOB_SUCCEEDED, "sent": RESULT_SENT,
                "requested": RESULT_FOLLOW_REQUESTED})).all()
            if not rows:
                raise HTTPException(400, "This campaign hasn't followed anyone yet")

            # One unfollow campaign per follow campaign. Clicking again adds
            # the people followed since — the importer skips anyone already
            # on it — instead of a second list repeating the first.
            existing = (await database.session.execute(text(
                "SELECT id FROM outreach_campaigns WHERE source_campaign_id = :cid "
                "   AND activity = :unfollow ORDER BY id DESC LIMIT 1"
            ), {"cid": campaign_id, "unfollow": ACTIVITY_UNFOLLOW})).first()
            csv_text = "username,profile_url\n" + "".join(
                f"{r[0]},{r[1] or ''}\n" for r in rows)
            if existing:
                target_id = int(existing[0])
                summary = await importer.import_targets(database, target_id, csv_text, platform=platform)
                added = int(summary.get("ready", 0))
                if added:
                    await db.log_outreach_audit(
                        database, AUDIT_TARGETS_IMPORTED, "campaign", target_id, user_id=user["id"],
                        detail=f"{added} newly followed from campaign {campaign_id}",
                    )
                row = await db.get_outreach_campaign(database, target_id)
                return {"campaign": _campaign_public(dict(row)), "people": added, "created": False}

            name = f"Unfollow — {source.get('name') or f'campaign {campaign_id}'}"[:200]
            new_id = await db.create_outreach_campaign(
                database, user_id=source.get("user_id") or user["id"], name=name,
                description=f"Everyone “{source.get('name')}” followed.",
                message_template="", platform=platform, activity=ACTIVITY_UNFOLLOW,
                status=CAMPAIGN_DRAFT, source_campaign_id=campaign_id,
            )
            summary = await importer.import_targets(database, new_id, csv_text, platform=platform)
            for account_id in await db.get_campaign_account_ids(database, campaign_id):
                await db.assign_account_to_campaign(database, new_id, account_id)
            await db.log_outreach_audit(
                database, AUDIT_CAMPAIGN_CREATED, "campaign", new_id, user_id=user["id"],
                detail=f"{name}: {summary.get('ready', len(rows))} people from campaign {campaign_id}",
            )
            row = await db.get_outreach_campaign(database, new_id)
            return {"campaign": _campaign_public(dict(row)), "people": summary.get("ready", len(rows)),
                    "created": True}
        finally:
            await database.close()

    @router.post("/campaigns/{campaign_id}/import")
    async def import_targets_file(
        campaign_id: int,
        file: UploadFile = File(...),
        user: dict = Depends(get_current_user),
    ):
        """CSV upload. Accepts `username`, `profile_url`, or both."""
        database = await db.get_db()
        try:
            campaign = await _own_campaign(database, campaign_id, user)
            raw = await file.read()
            if len(raw) > MAX_IMPORT_BYTES:
                raise HTTPException(400, "File is too large (limit 20 MB)")
            return await _do_import(database, campaign, raw, user)
        finally:
            await database.close()

    @router.post("/campaigns/{campaign_id}/import-text")
    async def import_targets_text(
        campaign_id: int, data: TargetsPaste, user: dict = Depends(get_current_user)
    ):
        """Pasted list — same parser, same validation as the CSV path."""
        database = await db.get_db()
        try:
            campaign = await _own_campaign(database, campaign_id, user)
            return await _do_import(database, campaign, data.content or "", user)
        finally:
            await database.close()

    @router.get("/campaigns/{campaign_id}/targets")
    async def list_targets(
        campaign_id: int,
        status: Optional[str] = None,
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
        user: dict = Depends(get_current_user),
    ):
        database = await db.get_db()
        try:
            await _own_campaign(database, campaign_id, user)
            rows = await db.get_outreach_targets(
                database, campaign_id, status=status, limit=limit, offset=offset
            )
            counts = await db.count_outreach_targets(database, campaign_id)
            return {
                "targets": [_tag_utc(dict(r)) for r in rows],
                "counts": counts,
                "total": sum(counts.values()),
            }
        finally:
            await database.close()

    @router.get("/campaigns/{campaign_id}/export.csv")
    async def export_results(
        campaign_id: int,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        links_only: bool = False,
        user: dict = Depends(get_current_user),
    ):
        """The campaign's targets as CSV, filtered the way the page asks.

        `status` is a comma-separated list of target statuses — the usual
        ask is "just the ones still to do" or "just the skipped", and
        exporting all seven thousand to filter them in a spreadsheet is
        what people were doing instead.

        `limit` caps the rows. `links_only` drops the bookkeeping columns
        and leaves the handle and the profile link, which is the shape you
        want when the export is going somewhere that takes a list of links.
        """
        wanted: set[str] = set()
        if status:
            wanted = {s.strip().lower() for s in status.split(",") if s.strip()}
            unknown = sorted(wanted - set(TARGET_STATUSES))
            if unknown:
                raise HTTPException(
                    400,
                    f"Unknown status: {', '.join(unknown)}. Known: "
                    f"{', '.join(TARGET_STATUSES)}")
        if limit is not None and limit < 1:
            raise HTTPException(400, "limit must be 1 or more")

        database = await db.get_db()
        try:
            campaign = await _own_campaign(database, campaign_id, user)
            rows = await db.get_outreach_targets(database, campaign_id, limit=None)
            accounts = {
                int(a["id"]): a["name"]
                for a in await db.get_sending_accounts(database, user_id=campaign.get("user_id"))
            }
        finally:
            await database.close()

        platform = campaign.get("platform") or importer.DEFAULT_PLATFORM
        selected = [dict(r) for r in rows
                    if not wanted or (r["status"] or "").lower() in wanted]
        if limit is not None:
            selected = selected[:limit]

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        if links_only:
            writer.writerow(["username", "profile_url"])
        else:
            writer.writerow([
                "username", "profile_url", "status", "attempts",
                "sending_account", "last_attempt_at", "sent_at", "error_message",
            ])
        for item in selected:
            # Stored URLs are absolute and platform-correct today, but a
            # list imported as bare handles would have none — and an export
            # of blanks is worse than useless when the whole point is the
            # link. Rebuilt from the campaign's platform when it is missing.
            link = (item.get("profile_url") or "").strip()
            if not link:
                link = importer.profile_url_for(item.get("username") or "", platform)
            if links_only:
                writer.writerow([item.get("username"), link])
                continue
            writer.writerow([
                item.get("username"), link, item.get("status"),
                item.get("attempts"),
                accounts.get(item.get("assigned_account_id") or -1, ""),
                item.get("last_attempt_at") or "", item.get("sent_at") or "",
                (item.get("error_message") or "").replace("\n", " "),
            ])
        buffer.seek(0)
        # The filename says what is in it, so three exports taken a minute
        # apart are still tellable apart in a downloads folder.
        parts = [f"outreach-campaign-{campaign_id}", platform]
        if wanted:
            parts.append("-".join(sorted(wanted)))
        if links_only:
            parts.append("links")
        if limit is not None:
            parts.append(str(len(selected)))
        filename = "-".join(parts) + ".csv"
        return StreamingResponse(
            iter([buffer.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # --- controls --------------------------------------------------------

    async def _preflight(database, campaign: dict) -> list[str]:
        """Reasons this campaign cannot start. Empty list means go."""
        problems: list[str] = []
        # Only a message campaign sends a message. Checking the template on
        # the others refused every follow or unfollow campaign made from the
        # current dialog, which stores no message for them — "Message
        # template is empty" on a campaign that has none by design.
        if (campaign.get("activity") or ACTIVITY_MESSAGE) == ACTIVITY_MESSAGE:
            try:
                template_svc.validate_template(campaign.get("message_template") or "")
            except template_svc.TemplateError as exc:
                problems.append(str(exc))
        counts = await db.count_outreach_targets(database, campaign["id"])
        if counts.get("queued", 0) + counts.get("paused", 0) == 0:
            problems.append(
                "Nothing to comment — set the video and how many comments"
                if comments.is_comment(campaign)
                else "No queued targets — import a list first"
            )
        if not await account_mgr.eligible_account_ids(database, campaign):
            phone_only = any(
                (r.get("via") or ACCOUNT_VIA_BROWSER) == ACCOUNT_VIA_PHONE and r.get("enabled")
                for r in await db.get_sending_accounts(
                    database, user_id=campaign.get("user_id"), platform=campaign.get("platform"))
            ) and not account_mgr.phone_ok(campaign)
            problems.append(
                ("Phone accounts can't send images yet — remove the image, or use an "
                 "account signed in on the browser"
                 if campaign.get("attachment_path") else
                 "Phone accounts only do TikTok follows, unfollows and messages for now — "
                 "this campaign needs an account signed in on the browser")
                if phone_only else
                "No enabled sending account for this campaign — add one, or "
                "re-enable a paused account"
            )
        refused = campaign.get("refused_template")
        if refused and refused == (campaign.get("message_template") or ""):
            # Resuming on the same words sends them into the same refusal,
            # one flagged message at a time, from an account that did
            # nothing wrong.
            problems.append(
                "The platform refused this exact message — change the wording "
                "before starting again"
            )
        return problems

    @router.post("/campaigns/{campaign_id}/start")
    async def start_campaign(campaign_id: int, user: dict = Depends(get_current_user)):
        database = await db.get_db()
        try:
            campaign = await _own_campaign(database, campaign_id, user)
            # A comment campaign has no list of people — its targets are
            # the comments themselves. They are materialised before the
            # preflight, which would otherwise refuse a campaign for
            # having no targets a moment before it made them.
            if comments.is_comment(campaign):
                try:
                    await comments.sync_slots(database, campaign)
                except comments.CommentSetupError as exc:
                    raise HTTPException(400, {"errors": [str(exc)]}) from exc
            problems = await _preflight(database, campaign)
            if problems:
                raise HTTPException(400, {"errors": problems})
            settings = await cfg.get_all(database)
            created = await job_queue.start_campaign(database, campaign, settings)
            # Starting by hand clears a platform cooldown, exactly as
            # resuming does. Without this the campaign runs with a deadline
            # still set on it: the countdown does not show because the
            # status is `running`, and when that deadline passes the sweep
            # "resumes" a campaign that never stopped and logs a cooldown
            # clearing that nobody was waiting on.
            await db.update_outreach_campaign(
                database, campaign_id, paused_until=None, paused_reason=None,
                refused_template=None, refused_account_id=None)
            await db.log_outreach_audit(
                database, AUDIT_CAMPAIGN_STARTED, "campaign", campaign_id,
                user_id=user["id"],
                detail=(f"queued {created} job(s)"
                        + (f"; cleared a platform cooldown that had "
                           f"{_remaining_phrase(campaign.get('paused_until'))} left"
                           if campaign.get("paused_until") else "")),
            )
            row = await db.get_outreach_campaign(database, campaign_id)
            return {"ok": True, "jobs_queued": created, "campaign": _campaign_public(dict(row))}
        finally:
            await database.close()

    @router.post("/campaigns/{campaign_id}/pause")
    async def pause_campaign(campaign_id: int, user: dict = Depends(get_current_user)):
        database = await db.get_db()
        try:
            await _own_campaign(database, campaign_id, user)
            await job_queue.pause_campaign(database, campaign_id)
            await db.log_outreach_audit(
                database, AUDIT_CAMPAIGN_PAUSED, "campaign", campaign_id, user_id=user["id"]
            )
            row = await db.get_outreach_campaign(database, campaign_id)
            return {"ok": True, "campaign": _campaign_public(dict(row))}
        finally:
            await database.close()

    @router.post("/campaigns/{campaign_id}/resume")
    async def resume_campaign(campaign_id: int, user: dict = Depends(get_current_user)):
        database = await db.get_db()
        try:
            campaign = await _own_campaign(database, campaign_id, user)
            if campaign["status"] != CAMPAIGN_PAUSED:
                raise HTTPException(400, "Campaign is not paused")
            problems = await _preflight(database, campaign)
            if problems:
                raise HTTPException(400, {"errors": problems})
            settings = await cfg.get_all(database)
            created = await job_queue.resume_campaign(database, campaign, settings)
            # Resuming by hand overrides a platform cooldown. The operator
            # can see what the platform said and may know better — the app
            # tried it again on their say-so, not on the clock's. Clearing
            # the deadline also stops the sweep from "resuming" a campaign
            # that is already running and logging a cooldown that expired
            # after somebody had already dealt with it.
            await db.update_outreach_campaign(
                database, campaign_id, paused_until=None, paused_reason=None,
                refused_template=None, refused_account_id=None)
            await db.log_outreach_audit(
                database, AUDIT_CAMPAIGN_RESUMED, "campaign", campaign_id,
                user_id=user["id"],
                detail=(f"queued {created} job(s)"
                        + (f"; cleared a platform cooldown that had "
                           f"{_remaining_phrase(campaign.get('paused_until'))} left"
                           if campaign.get("paused_until") else "")),
            )
            row = await db.get_outreach_campaign(database, campaign_id)
            return {"ok": True, "jobs_queued": created, "campaign": _campaign_public(dict(row))}
        finally:
            await database.close()

    @router.post("/campaigns/{campaign_id}/stop")
    async def stop_campaign(campaign_id: int, user: dict = Depends(get_current_user)):
        database = await db.get_db()
        try:
            await _own_campaign(database, campaign_id, user)
            await job_queue.stop_campaign(database, campaign_id)
            await db.log_outreach_audit(
                database, AUDIT_CAMPAIGN_STOPPED, "campaign", campaign_id, user_id=user["id"]
            )
            row = await db.get_outreach_campaign(database, campaign_id)
            return {"ok": True, "campaign": _campaign_public(dict(row))}
        finally:
            await database.close()

    @router.post("/campaigns/{campaign_id}/attachment")
    async def set_campaign_attachment(
        campaign_id: int,
        file: UploadFile = File(...),
        user: dict = Depends(get_current_user),
    ):
        """Attach an image to every message this campaign sends."""
        data = await file.read()
        try:
            path, name = attachments.save(
                campaign_id, data, file.content_type, file.filename
            )
        except attachments.AttachmentError as exc:
            raise HTTPException(400, str(exc)) from exc

        database = await db.get_db()
        try:
            campaign = dict(await _own_campaign(database, campaign_id, user))
            # Replacing one leaves no orphan behind.
            attachments.remove(campaign.get("attachment_path"))
            await db.update_outreach_campaign(
                database, campaign_id, attachment_path=path, attachment_name=name
            )
            row = await db.get_outreach_campaign(database, campaign_id)
            return _campaign_public(dict(row))
        except Exception:
            # The row was not updated, so the file we just wrote is unreachable.
            attachments.remove(path)
            raise
        finally:
            await database.close()

    @router.delete("/campaigns/{campaign_id}/attachment")
    async def clear_campaign_attachment(
        campaign_id: int, user: dict = Depends(get_current_user)
    ):
        database = await db.get_db()
        try:
            campaign = dict(await _own_campaign(database, campaign_id, user))
            attachments.remove(campaign.get("attachment_path"))
            await db.update_outreach_campaign(
                database, campaign_id, attachment_path=None, attachment_name=None
            )
            row = await db.get_outreach_campaign(database, campaign_id)
            return _campaign_public(dict(row))
        finally:
            await database.close()

    @router.get("/campaigns/{campaign_id}/attachment")
    async def get_campaign_attachment(
        campaign_id: int, user: dict = Depends(get_current_user)
    ):
        """The image itself, for previewing it in the campaign page."""
        database = await db.get_db()
        try:
            campaign = dict(await _own_campaign(database, campaign_id, user))
        finally:
            await database.close()
        path = campaign.get("attachment_path")
        if not attachments.exists(path):
            raise HTTPException(404, "This campaign has no attachment.")
        return FileResponse(path)

    @router.get("/campaigns/{campaign_id}/watch")
    async def watch_status(campaign_id: int, user: dict = Depends(get_current_user)):
        """Whether a send can be watched here, and how the current one is going."""
        database = await db.get_db()
        try:
            await _own_campaign(database, campaign_id, user)
        finally:
            await database.close()

        watch = watch_run.status_for(campaign_id)
        sender = outreach_runner.local_worker_state()
        return {
            "available": watch_run.unavailable_reason() is None,
            "unavailable_reason": watch_run.unavailable_reason(),
            "running": watch_run.is_running(campaign_id),
            "busy_elsewhere": watch_run.any_running()
            and not watch_run.is_running(campaign_id),
            "watch": watch.to_dict() if watch else None,
            # When the local sender is up, campaigns send by themselves and
            # the window is already on screen — there is nothing to start.
            "sender_running": bool(sender.get("running")),
            "sender_busy": bool(sender.get("busy")),
            # How many accounts are mid-send, and how many windows there are
            # to be mid-send in.
            "sender_active": int(sender.get("busy") or 0),
            "sender_slots": int(sender.get("slots") or 0),
            "sender_error": sender.get("last_error"),
        }

    @router.post("/campaigns/{campaign_id}/watch")
    async def start_watch(campaign_id: int, user: dict = Depends(get_current_user)):
        """Run one job in a browser window, so a person can watch it.

        The driver already holds the page open for several minutes when a
        verification puzzle appears, because only a person can clear one.
        This is what gives them a window to clear it in.
        """
        reason = watch_run.unavailable_reason()
        if reason:
            raise HTTPException(400, reason)

        database = await db.get_db()
        try:
            campaign = dict(await _own_campaign(database, campaign_id, user))
        finally:
            await database.close()

        try:
            watch = watch_run.start(campaign)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return watch.to_dict()

    @router.post("/campaigns/{campaign_id}/retry-failed")
    async def retry_failed(campaign_id: int, user: dict = Depends(get_current_user)):
        database = await db.get_db()
        try:
            campaign = await _own_campaign(database, campaign_id, user)
            reset = await job_queue.retry_failed(database, campaign_id)
            created = 0
            if campaign["status"] == CAMPAIGN_RUNNING:
                settings = await cfg.get_all(database)
                created = await job_queue.enqueue_campaign(database, campaign, settings)
            await db.log_outreach_audit(
                database, AUDIT_CAMPAIGN_RETRY_FAILED, "campaign", campaign_id,
                user_id=user["id"], detail=f"reset {reset} target(s)",
            )
            return {"ok": True, "targets_reset": reset, "jobs_queued": created}
        finally:
            await database.close()

    # --- campaign ↔ account assignment ------------------------------------

    @router.post("/campaigns/{campaign_id}/accounts/{account_id}")
    async def assign_account(
        campaign_id: int, account_id: int, user: dict = Depends(get_current_user)
    ):
        database = await db.get_db()
        try:
            campaign = await _own_campaign(database, campaign_id, user)
            account = await _own_account(database, account_id, user)
            if account["platform"] != campaign["platform"]:
                raise HTTPException(
                    400,
                    f"Account is for {account['platform']}, campaign is for "
                    f"{campaign['platform']}",
                )
            await db.assign_account_to_campaign(database, campaign_id, account_id)
            await db.log_outreach_audit(
                database, AUDIT_ACCOUNT_ASSIGNED, "campaign", campaign_id,
                user_id=user["id"], detail=f"account_id={account_id}",
            )
            return {"ok": True, "assigned_account_ids":
                    await db.get_campaign_account_ids(database, campaign_id)}
        finally:
            await database.close()

    @router.delete("/campaigns/{campaign_id}/accounts/{account_id}")
    async def unassign_account(
        campaign_id: int, account_id: int, user: dict = Depends(get_current_user)
    ):
        database = await db.get_db()
        try:
            await _own_campaign(database, campaign_id, user)
            await db.unassign_account_from_campaign(database, campaign_id, account_id)
            await db.log_outreach_audit(
                database, AUDIT_ACCOUNT_UNASSIGNED, "campaign", campaign_id,
                user_id=user["id"], detail=f"account_id={account_id}",
            )
            return {"ok": True, "assigned_account_ids":
                    await db.get_campaign_account_ids(database, campaign_id)}
        finally:
            await database.close()

    # =====================================================================
    # Sending accounts
    # =====================================================================

    @router.get("/devices")
    async def list_devices(user: dict = Depends(get_current_user)):
        """Phones attached to the machine running the worker."""
        from services.outreach.browser.android_tiktok import connected_phones

        return await connected_phones()

    # =====================================================================
    # The phone app — TikTok follows without a cable (services/outreach/companion.py)
    # =====================================================================

    def _device(device_id: str) -> str:
        device = (device_id or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9-]{16,64}", device):
            raise HTTPException(400, "That is not a phone id this app would send")
        return device

    @router.get("/companion/accounts")
    async def companion_accounts(device_id: str = Query(...),
                                 user: dict = Depends(get_current_user)):
        """The caller's TikTok accounts, and which phone each one follows through."""
        device = _device(device_id)
        database = await db.get_db()
        try:
            rows = await db.get_sending_accounts(database, user_id=_scope(user))
            out = []
            for r in rows:
                a = dict(r)
                if (a.get("platform") or "") != "tiktok" or a.get("purpose") == "discovery":
                    continue
                linked = a.get("companion_device")
                out.append({
                    "id": a["id"], "name": a["name"], "enabled": a.get("enabled"),
                    "status": a.get("status"), "paused_reason": a.get("paused_reason"),
                    "handle": a.get("device_handle"),
                    "linked": "this" if linked == device else ("other" if linked else None),
                    "seen_at": _tag_utc({"t": a.get("companion_seen_at")})["t"],
                })
            return out
        finally:
            await database.close()

    @router.post("/companion/link")
    async def companion_link(data: CompanionLink, user: dict = Depends(get_current_user)):
        """This phone does this account's TikTok follows, signed in as `handle`."""
        device = _device(data.device_id)
        handle = (data.handle or "").strip().lstrip("@")
        if not re.fullmatch(r"[\w.]{1,30}", handle):
            raise HTTPException(400, "That does not look like a TikTok handle")
        database = await db.get_db()
        try:
            account = await _own_account(database, data.account_id, user)
            if account.get("platform") != "tiktok":
                raise HTTPException(400, "Only TikTok accounts follow through the phone app")
            await db.update_sending_account(
                database, data.account_id, companion_device=device, device_handle=handle,
                via=ACCOUNT_VIA_PHONE)
            await db.log_outreach_audit(
                database, AUDIT_ACCOUNT_UPDATED, "account", data.account_id,
                user_id=user["id"], detail=f"phone app linked for follows as @{handle}")
            return {"ok": True}
        finally:
            await database.close()

    @router.post("/companion/unlink/{account_id}")
    async def companion_unlink(account_id: int, data: CompanionDevice,
                               user: dict = Depends(get_current_user)):
        device = _device(data.device_id)
        database = await db.get_db()
        try:
            account = await _own_account(database, account_id, user)
            if account.get("companion_device") != device:
                raise HTTPException(409, "This account isn't linked to this phone")
            await db.update_sending_account(database, account_id, companion_device=None)
            await db.log_outreach_audit(
                database, AUDIT_ACCOUNT_UPDATED, "account", account_id,
                user_id=user["id"], detail="phone app unlinked")
            return {"ok": True}
        finally:
            await database.close()

    @router.post("/companion/next")
    async def companion_next(data: CompanionDevice, user: dict = Depends(get_current_user)):
        """The next follow for this phone, or none. The phone asks every few seconds."""
        device = _device(data.device_id)
        database = await db.get_db()
        try:
            return {"task": await companion.claim(database, device, _scope(user))}
        finally:
            await database.close()

    @router.post("/companion/tasks/{task_id}/result")
    async def companion_result(task_id: int, data: CompanionResult,
                               user: dict = Depends(get_current_user)):
        device = _device(data.device_id)
        if data.status not in companion.PHONE_RESULTS:
            raise HTTPException(400, f"Unknown result {data.status!r}")
        database = await db.get_db()
        try:
            # Only a phone that claimed the task under this user's account
            # can answer it; `finish` checks the device and the state.
            owner = (await database.session.execute(text(
                "SELECT a.user_id FROM outreach_companion_tasks t "
                "  JOIN outreach_sending_accounts a ON a.id = t.account_id WHERE t.id = :id"
            ), {"id": task_id})).first()
            if owner is None:
                raise HTTPException(404, "Task not found")
            if user.get("role") != "admin" and owner[0] != user["id"]:
                raise HTTPException(403, "Access denied")
            ok = await companion.finish(database, task_id, device, data.status,
                                        data.error, data.detail)
            if not ok:
                # Expired, answered already, or claimed by another phone.
                raise HTTPException(409, "That follow is no longer waiting for this phone")
            return {"ok": True}
        finally:
            await database.close()

    @router.get("/accounts")
    async def list_accounts(user: dict = Depends(get_current_user)):
        database = await db.get_db()
        try:
            rows = await db.get_sending_accounts(database, user_id=_scope(user))
            return [_account_public(dict(r)) for r in rows]
        finally:
            await database.close()

    @router.post("/accounts")
    async def create_account(data: AccountCreate, user: dict = Depends(get_current_user)):
        name = (data.name or "").strip()
        if not name:
            raise HTTPException(400, "Account name is required")
        if data.platform not in importer.PLATFORMS:
            raise HTTPException(400, f"Unsupported platform: {data.platform}")
        if data.purpose not in ACCOUNT_PURPOSES:
            raise HTTPException(
                400, f"purpose must be one of: {', '.join(ACCOUNT_PURPOSES)}"
            )

        database = await db.get_db()
        try:
            existing = await db.get_sending_accounts(database, user_id=user["id"])
            if len(existing) >= cfg.MAX_SENDING_ACCOUNTS:
                raise HTTPException(
                    400, f"Account limit reached ({cfg.MAX_SENDING_ACCOUNTS})"
                )
            account_id = await db.create_sending_account(
                database,
                user_id=user["id"],
                name=name,
                platform=data.platform,
                purpose=data.purpose,
                status=ACCOUNT_IDLE,
                session_reference=(data.session_reference or "").strip() or None,
                enabled=True,
            )
            await db.log_outreach_audit(
                database, AUDIT_ACCOUNT_CREATED, "account", account_id,
                user_id=user["id"], detail=name,
            )
            row = await db.get_sending_account(database, account_id)
            return _account_public(dict(row))
        finally:
            await database.close()

    @router.get("/accounts/{account_id}")
    async def get_account(account_id: int, user: dict = Depends(get_current_user)):
        database = await db.get_db()
        try:
            account = await _own_account(database, account_id, user)
            jobs = await db.get_outreach_jobs(database, account_id=account_id, limit=25)
            audit = await db.get_outreach_audit_logs(
                database, entity_type="account", entity_id=account_id, limit=25
            )
            return {
                "account": _account_public(account),
                "recent_jobs": [_tag_utc(dict(j)) for j in jobs],
                "audit": [_tag_utc(dict(a)) for a in audit],
            }
        finally:
            await database.close()

    @router.put("/accounts/{account_id}")
    async def update_account(
        account_id: int, data: AccountUpdate, user: dict = Depends(get_current_user)
    ):
        database = await db.get_db()
        try:
            account = await _own_account(database, account_id, user)
            updates: dict[str, Any] = {}
            if data.name is not None:
                if not data.name.strip():
                    raise HTTPException(400, "Account name cannot be empty")
                updates["name"] = data.name.strip()
            if data.session_reference is not None:
                updates["session_reference"] = data.session_reference.strip() or None
            if data.proxy_url is not None:
                # Blank clears it, which is how an account goes back to
                # this server's own address.
                try:
                    proxy = proxies.parse(data.proxy_url)
                except proxies.ProxyInvalid as exc:
                    raise HTTPException(400, str(exc)) from exc
                updates["proxy_url_encrypted"] = (
                    encrypt_session(data.proxy_url.strip()) if proxy else None
                )
            if data.device_serial is not None:
                updates["device_serial"] = data.device_serial.strip() or None
            if data.device_handle is not None:
                handle = data.device_handle.strip().lstrip("@")
                if handle and not re.fullmatch(r"[\w.]{1,30}", handle):
                    raise HTTPException(400, "That does not look like a TikTok handle")
                updates["device_handle"] = handle or None
            if data.via is not None:
                if data.via not in ACCOUNT_VIAS:
                    raise HTTPException(400, f"via must be one of: {', '.join(ACCOUNT_VIAS)}")
                if data.via == ACCOUNT_VIA_PHONE:
                    if account.get("platform") not in PHONE_PLATFORMS:
                        raise HTTPException(400, "Only TikTok accounts can work through the phone app yet")
                    if not (updates.get("device_handle") or account.get("device_handle")):
                        raise HTTPException(400, "Enter the TikTok username the phone is signed in as")
                updates["via"] = data.via
            if data.purpose is not None:
                if data.purpose not in ACCOUNT_PURPOSES:
                    raise HTTPException(
                        400, f"purpose must be one of: {', '.join(ACCOUNT_PURPOSES)}"
                    )
                # Changing this is allowed — an account moved to discovery
                # stops being leased for sending from the next claim, and
                # back again the same way. The session is untouched either
                # way, so nothing has to be signed in again.
                updates["purpose"] = data.purpose
            if data.enabled is not None:
                updates["enabled"] = bool(data.enabled)
                if data.enabled:
                    # Re-enabling clears an auto-pause; that is the whole
                    # point of the operator toggling it back on.
                    updates["status"] = ACCOUNT_IDLE
                    updates["paused_reason"] = None
                    updates["consecutive_errors"] = 0
            if updates:
                await db.update_sending_account(database, account_id, **updates)
            if data.enabled is not None:
                await db.log_outreach_audit(
                    database,
                    AUDIT_ACCOUNT_ENABLED if data.enabled else AUDIT_ACCOUNT_DISABLED,
                    "account", account_id, user_id=user["id"],
                )
            elif updates:
                await db.log_outreach_audit(
                    database, AUDIT_ACCOUNT_UPDATED, "account", account_id,
                    user_id=user["id"], detail=", ".join(sorted(updates)),
                )
            row = await db.get_sending_account(database, account_id)
            return _account_public(dict(row))
        finally:
            await database.close()

    @router.post("/accounts/{account_id}/proxy/test")
    async def test_account_proxy(
        account_id: int, user: dict = Depends(get_current_user)
    ):
        """Prove the proxy carries traffic, and that it changes the address.

        A dead or mistyped proxy does not announce itself: Chromium falls
        back to the host's own connection and everything looks healthy,
        which is the failure this feature exists to prevent. So the answer
        is the address the world actually sees, next to this server's, and
        the two being equal is reported as a problem rather than a pass.
        """
        database = await db.get_db()
        try:
            row = dict(await _own_account(database, account_id, user))
        finally:
            await database.close()

        try:
            proxy = proxies.parse(decrypt_session(row.get("proxy_url_encrypted")))
        except proxies.ProxyInvalid as exc:
            raise HTTPException(400, str(exc)) from exc
        if proxy is None:
            raise HTTPException(400, "This account has no proxy set")

        try:
            through = await proxies.egress_ip(proxy)
            direct = await proxies.egress_ip(None)
        except Exception as exc:  # noqa: BLE001 — the operator needs the reason
            raise HTTPException(
                400, f"The proxy did not carry a page: {type(exc).__name__}: "
                     f"{str(exc)[:200]}") from exc

        return {
            "proxy": proxy.safe,
            "egress_ip": through,
            "server_ip": direct,
            "ok": bool(through) and through != direct,
            "detail": (
                "Traffic is going out through the proxy."
                if through and through != direct
                else "The proxy is not changing the address — this account "
                     "is still sending from the server itself."
            ),
        }

    @router.post("/accounts/{account_id}/session")
    async def set_account_session(
        account_id: int, data: AccountSession, user: dict = Depends(get_current_user)
    ):
        """Store an authorized browser session for this account.

        The operator signs in themselves and uploads the resulting
        Playwright storage-state JSON; it is encrypted at rest and never
        read back out through the API. No password ever reaches this
        service.
        """
        if not crypto_available():
            raise HTTPException(
                500,
                "Session encryption is not configured on the backend — its "
                "session secret has to be set before an account can be signed in",
            )
        raw = data.session_state
        if isinstance(raw, (dict, list)):
            raw = json.dumps(raw)
        if not isinstance(raw, str) or not raw.strip():
            raise HTTPException(400, "session_state must be JSON")
        try:
            parsed = json.loads(raw)
        except ValueError as exc:
            raise HTTPException(400, "session_state is not valid JSON") from exc
        if not isinstance(parsed, dict) or not (
            parsed.get("cookies") or parsed.get("origins")
        ):
            raise HTTPException(
                400,
                "session_state does not look like a Playwright storage state "
                "(expected 'cookies' and/or 'origins')",
            )

        database = await db.get_db()
        try:
            account = await _own_account(database, account_id, user)
            await db.update_sending_account(
                database, account_id,
                session_state_encrypted=encrypt_session(raw),
                session_reference=(
                    (data.session_reference or "").strip()
                    or account.get("session_reference")
                    or f"session/account-{account_id}"
                ),
                session_updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
                status=ACCOUNT_IDLE,
                paused_reason=None,
                consecutive_errors=0,
            )
            await db.log_outreach_audit(
                database, AUDIT_ACCOUNT_SESSION_SET, "account", account_id,
                user_id=user["id"], detail=f"{len(parsed.get('cookies') or [])} cookie(s)",
            )
            row = await db.get_sending_account(database, account_id)
            return _account_public(dict(row))
        finally:
            await database.close()

    @router.get("/accounts/{account_id}/session/browser")
    async def browser_login_status(
        account_id: int, user: dict = Depends(get_current_user)
    ):
        """Whether a browser sign-in can run here, and how one is going.

        Polled while a window is open — signing in takes minutes, which is
        far longer than a request should be held.
        """
        database = await db.get_db()
        try:
            await _own_account(database, account_id, user)
        finally:
            await database.close()

        reason = session_capture.unavailable_reason()
        capture = session_capture.status_for(account_id)
        return {
            "available": reason is None,
            "unavailable_reason": reason,
            "running": session_capture.is_running(account_id),
            "capture": capture.to_dict() if capture else None,
        }

    @router.post("/accounts/{account_id}/session/browser")
    async def start_browser_login(
        account_id: int, reuse: bool = False, user: dict = Depends(get_current_user)
    ):
        """Open a real login window so the operator can sign in by hand.

        No password reaches this service: a browser opens on the machine
        running the backend, the person signs in, and the resulting session
        is encrypted straight into the account row.

        Only ever offered where someone can see the window — see
        `session_capture.is_enabled`.
        """
        reason = session_capture.unavailable_reason()
        if reason:
            raise HTTPException(400, reason)

        database = await db.get_db()
        try:
            account = dict(await _own_account(database, account_id, user))
        finally:
            await database.close()

        # `?reuse=true`: open the saved session, signed in, instead of a
        # sign-in page — to clear a verification puzzle as the account.
        try:
            capture = session_capture.start(account, reuse=reuse)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return capture.to_dict()

    @router.post("/accounts/{account_id}/session/viewer-ticket")
    async def issue_viewer_ticket(
        account_id: int, user: dict = Depends(get_current_user)
    ):
        """A short-lived pass to watch this account's sign-in from the page.

        The sign-in browser runs on the server. Rather than asking a customer
        to paste a Playwright session — which nobody outside this team can
        produce — the page shows them that browser and lets them log in as
        they normally would.

        The ticket is what makes that safe to expose: minted only for the
        signed-in owner of this account, good for one socket, and expiring in
        under a minute.
        """
        reason = session_capture.unavailable_reason()
        if reason:
            raise HTTPException(400, reason)
        database = await db.get_db()
        try:
            await _own_account(database, account_id, user)
        finally:
            await database.close()
        # The screen this capture took, so the ticket opens that one and
        # no other. Without it every ticket reached the same display, which
        # is every session running on it.
        capture = session_capture.status_for(account_id)
        ticket = session_viewer.issue(
            session_viewer.KIND_ACCOUNT, account_id, user.get("id"),
            vnc_port=getattr(capture, "vnc_port", None) if capture else None,
        )
        return {
            "ticket": ticket.value,
            "expires_in": session_viewer.TICKET_TTL_SECONDS,
            "path": f"/api/outreach/accounts/{account_id}/session/stream",
        }

    async def _relay_vnc(websocket: WebSocket, ticket) -> None:
        """Pipe one screen to one page, both ways, until either goes.

        Shared by signing an account in and watching a campaign run: the
        only difference between them is which screen the ticket names, and
        duplicating this is how the two drift apart.
        """
        await websocket.accept()
        try:
            reader, writer = await asyncio.open_connection(
                session_viewer.VNC_HOST, ticket.vnc_port)
        except OSError as exc:
            print(f"[viewer] no VNC at {session_viewer.VNC_HOST}:"
                  f"{ticket.vnc_port}: {exc}", flush=True)
            await websocket.close(code=1011)
            return

        # Nagle's algorithm holds a small write back until the previous one
        # is acknowledged, and every pointer event is six bytes. Combined
        # with delayed acknowledgements that is tens of milliseconds added to
        # each one, which is felt as a mouse that arrives late and clicks
        # that land after the fact.
        try:
            sock = writer.get_extra_info("socket")
            if sock is not None:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:  # noqa: BLE001 — an optimisation, not a step
            pass

        # Answer the password step here, so the page never needs the VNC
        # password and the port keeps its protection from anything else
        # local on this host.
        problem = await session_viewer.negotiate(
            reader, writer,
            send=websocket.send_bytes,
            receive=websocket.receive_bytes,
        )
        if problem:
            print(f"[viewer] handshake failed: {problem}", flush=True)
            writer.close()
            await websocket.close(code=1011)
            return

        async def to_vnc() -> None:
            try:
                while True:
                    writer.write(await websocket.receive_bytes())
                    await writer.drain()
            except (WebSocketDisconnect, RuntimeError, ConnectionError):
                pass

        async def to_browser() -> None:
            try:
                while True:
                    chunk = await reader.read(65536)
                    if not chunk:
                        return
                    await websocket.send_bytes(chunk)
            except (WebSocketDisconnect, RuntimeError, ConnectionError):
                pass

        try:
            done, pending = await asyncio.wait(
                {asyncio.create_task(to_vnc()), asyncio.create_task(to_browser())},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001 — the peer went first
                pass

    @router.post("/campaigns/{campaign_id}/watch/viewer-ticket")
    async def campaign_viewer_ticket(
        campaign_id: int, user: dict = Depends(get_current_user)
    ):
        """A one-time pass to watch this campaign's browser work.

        The same mechanism as signing an account in, pointed at the run
        instead — which is what makes a verification puzzle solvable by the
        person whose campaign it is, rather than only by someone with an
        SSH tunnel.
        """
        reason = watch_run.unavailable_reason()
        if reason:
            raise HTTPException(400, reason)
        database = await db.get_db()
        try:
            await _own_campaign(database, campaign_id, user)
        finally:
            await database.close()
        watch = watch_run.status_for(campaign_id)
        if watch is None or watch.done:
            raise HTTPException(400, "No watched run is open for this campaign")
        ticket = session_viewer.issue(
            session_viewer.KIND_CAMPAIGN, campaign_id, user.get("id"),
            vnc_port=getattr(watch, "vnc_port", None),
        )
        return {
            "ticket": ticket.value,
            "expires_in": session_viewer.TICKET_TTL_SECONDS,
            "path": f"/api/outreach/campaigns/{campaign_id}/watch/stream",
        }

    @router.websocket("/campaigns/{campaign_id}/watch/stream")
    async def stream_campaign_browser(websocket: WebSocket, campaign_id: int):
        """The watched run's screen, both ways. See the account version."""
        ticket = session_viewer.redeem(
            websocket.query_params.get("ticket", ""),
            session_viewer.KIND_CAMPAIGN, campaign_id)
        if ticket is None:
            await websocket.close(code=1008)
            return
        await _relay_vnc(websocket, ticket)

    @router.websocket("/accounts/{account_id}/session/stream")
    async def stream_session_browser(websocket: WebSocket, account_id: int):
        """Pipe the sign-in browser's screen to the page, both ways.

        A plain byte relay between the customer's websocket and the local VNC
        server: their keystrokes and clicks go one way, the screen comes back
        the other. Nothing is interpreted here.

        Authentication is the ticket in the query string, because a browser
        cannot put an Authorization header on a websocket. It is spent the
        moment it is read, so the URL being written to a log is not a way in.
        """
        # Keep what redeeming returns: it carries which screen this ticket
        # opens, and the whole isolation rests on connecting to that one.
        ticket = session_viewer.redeem(
            websocket.query_params.get("ticket", ""),
            session_viewer.KIND_ACCOUNT, account_id)
        if ticket is None:
            # 1008 = policy violation. Closed before the VNC socket is even
            # opened, so an unauthenticated caller never reaches it.
            await websocket.close(code=1008)
            return
        await _relay_vnc(websocket, ticket)


    @router.post("/accounts/{account_id}/resume")
    async def resume_account(account_id: int, user: dict = Depends(get_current_user)):
        """Clear an auto-pause after the operator has fixed the cause."""
        database = await db.get_db()
        try:
            account = await _own_account(database, account_id, user)
            if account.get("status") != ACCOUNT_PAUSED:
                return _account_public(account)
            await account_mgr.resume_account(database, account_id)
            await db.log_outreach_audit(
                database, AUDIT_ACCOUNT_ENABLED, "account", account_id,
                user_id=user["id"], detail="auto-pause cleared",
            )
            row = await db.get_sending_account(database, account_id)
            return _account_public(dict(row))
        finally:
            await database.close()

    @router.delete("/accounts/{account_id}")
    async def delete_account(account_id: int, user: dict = Depends(get_current_user)):
        database = await db.get_db()
        try:
            account = await _own_account(database, account_id, user)
            await db.delete_sending_account(database, account_id)
            await db.log_outreach_audit(
                database, AUDIT_ACCOUNT_DELETED, "account", account_id,
                user_id=user["id"], detail=account.get("name"),
            )
            return {"ok": True}
        finally:
            await database.close()

    # =====================================================================
    # Lead discovery
    # =====================================================================

    @router.get("/leads/availability")
    async def lead_search_availability(
        platform: str = Query("instagram"), user: dict = Depends(get_current_user)
    ):
        """Can a search run here, with which account, and how much is left?"""
        database = await db.get_db()
        try:
            settings = await cfg.get_all(database)
            accounts = await discovery.discovery_accounts(
                database, platform, _scope(user)
            )
            budgets = []
            for account in accounts:
                # Still reported, because knowing how hard an account has
                # been worked today is useful. It no longer stops anything.
                used = await discovery.visited_today(database, int(account["id"]))
                budgets.append({
                    "id": account["id"],
                    "name": account["name"],
                    "used_today": used,
                })
        finally:
            await database.close()

        reason = discovery.unavailable_reason()
        if reason is None and not accounts:
            reason = (
                f"No {platform} discovery account connected. Add an account "
                f"with its purpose set to discovery, then sign it in — "
                f"harvesting should never run on the account you send from."
            )
        busy_reason = discovery.why_not_now(accounts, settings) if accounts else None
        busy_ids = discovery.busy_account_ids()
        for b in budgets:
            b["busy"] = int(b["id"]) in busy_ids
        return {
            "available": reason is None,
            "unavailable_reason": reason,
            # True only when no new search can start at all; a busy account
            # is reported on the account, and another one can be used.
            "busy": busy_reason is not None,
            "busy_reason": busy_reason,
            "running": discovery.running_count(),
            "accounts": budgets,
            "max_per_search": int(settings["outreach_discovery_max_per_search"]),
        }

    @router.post("/campaigns/{campaign_id}/leads/search")
    async def start_lead_search(
        campaign_id: int, data: LeadSearchCreate,
        user: dict = Depends(get_current_user),
    ):
        """Look for profiles matching a description, in a visible browser."""
        reason = discovery.unavailable_reason()
        if reason:
            raise HTTPException(400, reason)
        if not (data.niche or "").strip() and not (data.seed_accounts or "").strip():
            raise HTTPException(
                400,
                "Describe who you are looking for, or name accounts whose "
                "followers to read.",
            )

        database = await db.get_db()
        try:
            campaign = dict(await _own_campaign(database, campaign_id, user))
            platform = data.platform or campaign.get("platform") or "instagram"
            accounts = await discovery.discovery_accounts(
                database, platform, _scope(user)
            )
            if not accounts:
                raise HTTPException(
                    400,
                    f"No {platform} discovery account is connected. Add one "
                    f"with purpose 'discovery' and sign it in first.",
                )
            settings = await cfg.get_all(database)
            # Asked first, before a search row exists: refusing after the
            # insert left a "queued" search behind that nothing would run.
            not_now = discovery.why_not_now(accounts, settings)
            if not_now:
                raise HTTPException(409, not_now)
            busy = discovery.busy_account_ids()
            free = [a for a in accounts if int(a["id"]) not in busy]
            # The one asked for if it is free, otherwise any free one.
            account = next(
                (a for a in free if a["id"] == data.account_id), free[0]
            )

            row = (await database.session.execute(
                text(
                    "INSERT INTO outreach_lead_searches "
                    "  (user_id, campaign_id, platform, niche, location, "
                    "   interests, wanted, include_commenters, include_likers, "
                    "   include_replies, enrich_profiles, seed_accounts, "
                    "   account_id, status) "
                    "VALUES (:uid, :cid, :platform, :niche, :loc, :interests, "
                    "        :wanted, :commenters, :likers, :replies, :enrich, "
                    "        :seeds, :aid, :status) RETURNING id"
                ),
                {
                    "uid": user["id"], "cid": campaign_id, "platform": platform,
                    "niche": data.niche.strip(),
                    "loc": (data.location or "").strip() or None,
                    "interests": (data.interests or "").strip() or None,
                    "wanted": max(1, int(data.wanted or 50)),
                    "commenters": bool(data.include_commenters),
                    "likers": bool(data.include_likers),
                    "replies": bool(data.include_replies),
                    "enrich": bool(data.enrich_profiles),
                    "seeds": (data.seed_accounts or "").strip() or None,
                    "aid": int(account["id"]), "status": discovery.STATUS_QUEUED,
                },
            )).first()
            await database.session.commit()
            search_id = int(row[0])
            search = {
                "id": search_id, "user_id": user["id"], "platform": platform,
                "niche": (data.niche or "").strip(),
                "seed_accounts": (data.seed_accounts or "").strip() or None,
                "location": data.location,
                "interests": data.interests, "wanted": data.wanted,
                "include_commenters": bool(data.include_commenters),
                "include_likers": bool(data.include_likers),
                "include_replies": bool(data.include_replies),
                "enrich_profiles": bool(data.enrich_profiles),
            }
        finally:
            await database.close()

        try:
            run = discovery.start(search, account, settings)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return run.to_dict()

    @router.get("/leads/searches/{search_id}")
    async def lead_search_status(
        search_id: int, user: dict = Depends(get_current_user)
    ):
        database = await db.get_db()
        try:
            row = (await database.session.execute(
                text(
                    "SELECT * FROM outreach_lead_searches "
                    " WHERE id = :id AND (user_id = :uid OR :uid IS NULL)"
                ),
                {"id": search_id, "uid": _scope(user)},
            )).mappings().first()
        finally:
            await database.close()
        if not row:
            raise HTTPException(404, "No such search.")

        live = discovery.status_for(search_id)
        stored = _tag_utc(dict(row))
        return {
            "search": stored,
            "run": live.to_dict() if live else None,
            "running": discovery.is_running(search_id),
        }

    @router.post("/leads/searches/{search_id}/cancel")
    async def cancel_lead_search(
        search_id: int, user: dict = Depends(get_current_user)
    ):
        database = await db.get_db()
        try:
            row = (await database.session.execute(
                text(
                    "SELECT id FROM outreach_lead_searches "
                    " WHERE id = :id AND (user_id = :uid OR :uid IS NULL)"
                ),
                {"id": search_id, "uid": _scope(user)},
            )).first()
        finally:
            await database.close()
        if not row:
            raise HTTPException(404, "No such search.")
        was_running = discovery.cancel(search_id)
        if not was_running:
            # The row says `running` and there is no task behind it — the
            # process that owned it is gone. Nothing else will ever finish
            # that row, so Stop has to, or it stays "running" forever and
            # the button goes on doing nothing every time it is pressed.
            database = await db.get_db()
            try:
                await database.session.execute(
                    text(
                        "UPDATE outreach_lead_searches "
                        "   SET status = :cancelled, "
                        "       message = 'Stopped. The run was no longer "
                        "active — nothing was lost.', "
                        "       finished_at = (NOW() AT TIME ZONE 'UTC') "
                        " WHERE id = :id AND status IN ('queued', 'running')"
                    ),
                    {"id": search_id, "cancelled": discovery.STATUS_CANCELLED},
                )
                await database.session.commit()
            finally:
                await database.close()
        return {"ok": True, "was_running": was_running}

    @router.get("/leads/searches/{search_id}/leads")
    async def list_leads(
        search_id: int, user: dict = Depends(get_current_user),
        limit: Optional[int] = Query(None, ge=1),
    ):
        """Everything a search found, best first. Unscored leads sort last.

        No limit unless one is asked for (`LIMIT NULL` is no limit). A
        default of 500 once made a 638-lead search show 500 when it stopped,
        and "Select all" import 500 of them.
        """
        database = await db.get_db()
        try:
            rows = (await database.session.execute(
                text(
                    "SELECT l.* FROM outreach_leads l "
                    "  JOIN outreach_lead_searches s ON s.id = l.search_id "
                    " WHERE l.search_id = :id AND (s.user_id = :uid OR :uid IS NULL) "
                    " ORDER BY l.score DESC NULLS LAST, l.id ASC LIMIT :limit"
                ),
                {"id": search_id, "uid": _scope(user), "limit": limit},
            )).mappings().all()
            return [_tag_utc(dict(r)) for r in rows]
        finally:
            await database.close()

    @router.get("/leads/pending")
    async def pending_leads(
        platform: str = Query("instagram"),
        user: dict = Depends(get_current_user),
        limit: Optional[int] = Query(None, ge=1),
    ):
        """Leads found by past searches that never made it into a campaign.

        They are excluded from new searches — already found — and they are
        in no campaign, so without this they are stranded: discovery will
        not return them again and nothing will ever send to them. They are
        already in the database, so recovering them costs no browsing at
        all.
        """
        database = await db.get_db()
        try:
            rows = (await database.session.execute(
                text(
                    "SELECT l.* FROM outreach_leads l "
                    "  JOIN outreach_lead_searches s ON s.id = l.search_id "
                    " WHERE l.platform = :platform "
                    "   AND l.imported_at IS NULL "
                    "   AND (s.user_id = :uid OR :uid IS NULL) "
                    "   AND l.username NOT IN ( "
                    "       SELECT t.username FROM outreach_targets t "
                    "         JOIN outreach_campaigns c ON c.id = t.campaign_id "
                    "        WHERE c.platform = :platform) "
                    " ORDER BY l.score DESC NULLS LAST, l.id ASC LIMIT :limit"
                ),
                {"platform": platform, "uid": _scope(user), "limit": limit},
            )).mappings().all()
            return [_tag_utc(dict(r)) for r in rows]
        finally:
            await database.close()

    @router.post("/campaigns/{campaign_id}/leads/import")
    async def import_leads(
        campaign_id: int, data: LeadImport,
        user: dict = Depends(get_current_user),
    ):
        """Promote chosen leads into this campaign's targets."""
        if not data.lead_ids:
            raise HTTPException(400, "Pick at least one lead.")

        database = await db.get_db()
        try:
            wanted_ids = list(data.campaign_ids or [campaign_id])
            campaigns = [
                dict(await _own_campaign(database, cid, user)) for cid in wanted_ids
            ]
            platforms = {c["platform"] for c in campaigns}
            if len(platforms) > 1:
                raise HTTPException(
                    400,
                    f"Those campaigns are on different platforms "
                    f"({', '.join(sorted(platforms))}) — leads can only be split "
                    f"between campaigns on the same one.",
                )

            rows = (await database.session.execute(
                text(
                    "SELECT l.* FROM outreach_leads l "
                    "  JOIN outreach_lead_searches s ON s.id = l.search_id "
                    " WHERE l.id = ANY(:ids) AND (s.user_id = :uid OR :uid IS NULL)"
                ),
                {"ids": list(data.lead_ids), "uid": _scope(user)},
            )).mappings().all()
            leads = [dict(r) for r in rows]
            wrong = [l for l in leads if l["platform"] not in platforms]
            if wrong:
                raise HTTPException(
                    400,
                    f"{len(wrong)} lead(s) are {wrong[0]['platform']} but these "
                    f"campaigns are {platforms.pop()}.",
                )

            # Dealt round-robin, not in blocks. The list arrives best-first,
            # so splitting it down the middle would hand one campaign every
            # good lead and the other the remainder.
            buckets: dict[int, list[dict]] = {c["id"]: [] for c in campaigns}
            for index, lead in enumerate(leads):
                buckets[campaigns[index % len(campaigns)]["id"]].append(lead)

            per_campaign = []
            for campaign in campaigns:
                share = buckets[campaign["id"]]
                if not share:
                    continue
                summary = await importer.import_targets(
                    database, campaign["id"],
                    "\n".join(l["profile_url"] for l in share),
                    campaign["platform"],
                )
                per_campaign.append({
                    "campaign_id": campaign["id"],
                    "campaign_name": campaign["name"],
                    **summary,
                })

            await database.session.execute(
                text(
                    "UPDATE outreach_leads SET imported_at = NOW() "
                    " WHERE id = ANY(:ids)"
                ),
                {"ids": [l["id"] for l in leads]},
            )
            await database.session.commit()
            for campaign in campaigns:
                await stats.refresh_campaign_totals(database, campaign["id"])

            total_ready = sum(int(c.get("ready") or 0) for c in per_campaign)
            return {
                "ready": total_ready,
                "imported": sum(int(c.get("imported") or 0) for c in per_campaign),
                "duplicates": sum(int(c.get("duplicates") or 0) for c in per_campaign),
                "invalid": sum(int(c.get("invalid") or 0) for c in per_campaign),
                "invalid_rows": [],
                "campaigns": per_campaign,
            }
        finally:
            await database.close()

    # =====================================================================
    # Templates
    # =====================================================================

    @router.get("/templates")
    async def list_templates(user: dict = Depends(get_current_user)):
        database = await db.get_db()
        try:
            rows = await db.get_outreach_templates(database, user_id=_scope(user))
            return [_template_public(dict(r)) for r in rows]
        finally:
            await database.close()

    @router.post("/templates")
    async def create_template(data: TemplateCreate, user: dict = Depends(get_current_user)):
        if not (data.name or "").strip():
            raise HTTPException(400, "Template name is required")
        try:
            template_svc.validate_template(data.body)
        except template_svc.TemplateError as exc:
            raise HTTPException(400, str(exc)) from exc
        database = await db.get_db()
        try:
            template_id = await db.create_outreach_template(
                database, user_id=user["id"], name=data.name.strip(), body=data.body,
                defaults=template_svc.dump_vars(data.defaults),
            )
            row = await db.get_outreach_template(database, template_id)
            return _template_public(dict(row))
        finally:
            await database.close()

    @router.post("/templates/{template_id}/attachment")
    async def set_template_attachment(
        template_id: int,
        file: UploadFile = File(...),
        user: dict = Depends(get_current_user),
    ):
        """Attach an image to this template, inherited by new campaigns."""
        data = await file.read()
        try:
            path, name = attachments.save(
                template_id, data, file.content_type, file.filename, kind="template"
            )
        except attachments.AttachmentError as exc:
            raise HTTPException(400, str(exc)) from exc

        database = await db.get_db()
        try:
            template = dict(await _own_template(database, template_id, user))
            attachments.remove(template.get("attachment_path"))
            await db.update_outreach_template(
                database, template_id, attachment_path=path, attachment_name=name
            )
            return _template_public(dict(await db.get_outreach_template(database, template_id)))
        except Exception:
            attachments.remove(path)
            raise
        finally:
            await database.close()

    @router.delete("/templates/{template_id}/attachment")
    async def clear_template_attachment(
        template_id: int, user: dict = Depends(get_current_user)
    ):
        database = await db.get_db()
        try:
            template = dict(await _own_template(database, template_id, user))
            attachments.remove(template.get("attachment_path"))
            await db.update_outreach_template(
                database, template_id, attachment_path=None, attachment_name=None
            )
            return _template_public(dict(await db.get_outreach_template(database, template_id)))
        finally:
            await database.close()

    @router.get("/templates/{template_id}/attachment")
    async def get_template_attachment(
        template_id: int, user: dict = Depends(get_current_user)
    ):
        database = await db.get_db()
        try:
            template = dict(await _own_template(database, template_id, user))
        finally:
            await database.close()
        path = template.get("attachment_path")
        if not attachments.exists(path):
            raise HTTPException(404, "This template has no attachment.")
        return FileResponse(path)

    @router.put("/templates/{template_id}")
    async def update_template(
        template_id: int, data: TemplateUpdate, user: dict = Depends(get_current_user)
    ):
        database = await db.get_db()
        try:
            await _own_template(database, template_id, user)
            updates: dict[str, Any] = {}
            if data.name is not None:
                updates["name"] = data.name.strip()
            if data.body is not None:
                try:
                    template_svc.validate_template(data.body)
                except template_svc.TemplateError as exc:
                    raise HTTPException(400, str(exc)) from exc
                updates["body"] = data.body
            if data.defaults is not None:
                updates["defaults"] = template_svc.dump_vars(data.defaults)
            if updates:
                await db.update_outreach_template(database, template_id, **updates)
            row = await db.get_outreach_template(database, template_id)
            return _template_public(dict(row))
        finally:
            await database.close()

    @router.delete("/templates/{template_id}")
    async def delete_template(template_id: int, user: dict = Depends(get_current_user)):
        database = await db.get_db()
        try:
            await _own_template(database, template_id, user)
            await db.delete_outreach_template(database, template_id)
            return {"ok": True}
        finally:
            await database.close()

    @router.post("/templates/preview")
    async def preview_template(data: TemplatePreview, user: dict = Depends(get_current_user)):
        """Render with sample values — what the editor shows as you type."""
        try:
            return {
                "variables": template_svc.validate_template(data.body),
                "preview": template_svc.preview(data.body, data.variables),
            }
        except template_svc.TemplateError as exc:
            raise HTTPException(400, str(exc)) from exc

    # =====================================================================
    # Admin controls
    # =====================================================================

    @router.get("/settings")
    async def get_settings(admin: dict = Depends(admin_required)):
        database = await db.get_db()
        try:
            return {
                "values": await cfg.get_all(database),
                "spec": {k: {"default": d, "min": lo, "max": hi}
                         for k, (d, lo, hi) in cfg.SPEC.items()},
                "drivers": sorted(DRIVERS),
                "max_sending_accounts": cfg.MAX_SENDING_ACCOUNTS,
            }
        finally:
            await database.close()

    @router.put("/settings")
    async def update_settings(data: SettingsUpdate, admin: dict = Depends(admin_required)):
        """Write outreach settings into site_config.

        Only keys this module defines are accepted — the endpoint cannot be
        used as a generic write into `site_config`.
        """
        allowed = set(cfg.SPEC) | {cfg.DRIVER_KEY, cfg.WORKERS_ENABLED_KEY}
        unknown = sorted(set(data.values) - allowed)
        if unknown:
            raise HTTPException(400, f"Unknown setting(s): {', '.join(unknown)}")
        if cfg.DRIVER_KEY in data.values and data.values[cfg.DRIVER_KEY] not in (
            set(DRIVERS) | {cfg.DRIVER_AUTO}
        ):
            raise HTTPException(
                400,
                f"Unknown driver. Available: {cfg.DRIVER_AUTO} (route by platform), "
                f"{', '.join(sorted(DRIVERS))}",
            )

        database = await db.get_db()
        try:
            for key, value in data.values.items():
                if key == cfg.WORKERS_ENABLED_KEY:
                    value = "1" if value in (True, "1", "true", "on", 1) else "0"
                await db.set_site_config(database, key, str(value))
            await db.log_outreach_audit(
                database, AUDIT_WORKERS_TOGGLED, "settings", None,
                user_id=admin["id"], detail=json.dumps(data.values)[:1000],
            )
            return {"values": await cfg.get_all(database)}
        finally:
            await database.close()

    @router.get("/audit")
    async def list_audit(
        entity_type: Optional[str] = None,
        entity_id: Optional[int] = None,
        limit: int = Query(100, ge=1, le=500),
        user: dict = Depends(get_current_user),
    ):
        database = await db.get_db()
        try:
            rows = await db.get_outreach_audit_logs(
                database, entity_type=entity_type, entity_id=entity_id,
                user_id=_scope(user), limit=limit,
            )
            return [_tag_utc(dict(r)) for r in rows]
        finally:
            await database.close()

    return router
