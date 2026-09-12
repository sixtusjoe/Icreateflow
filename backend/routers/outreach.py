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
import io
import json
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import text

import database as db
from services.outreach import accounts as account_mgr
from services.outreach import config as cfg
from services.outreach import attachments, discovery, importer, session_capture, watch_run
from services.outreach import runner as outreach_runner
from services.outreach import queue as job_queue
from services.outreach import stats
from services.outreach import templates as template_svc
from services.outreach.browser import DRIVERS
from services.outreach.constants import (
    ACTIVITY_FOLLOW,
    ACTIVITY_MESSAGE,
    CAMPAIGN_ACTIVITIES,
    ACCOUNT_IDLE,
    ACCOUNT_PURPOSE_SENDING,
    ACCOUNT_PURPOSES,
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
from services.outreach.crypto import crypto_available, encrypt_session

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
    #: "message" (default) or "follow".
    activity: str = ACTIVITY_MESSAGE
    max_jobs: Optional[int] = None
    max_jobs_per_account: Optional[int] = None
    retry_limit: Optional[int] = None


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    activity: Optional[str] = None
    description: Optional[str] = None
    message_template: Optional[str] = None
    template_id: Optional[int] = None
    template_vars: Optional[dict[str, Any]] = None
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
    name: Optional[str] = None
    enabled: Optional[bool] = None
    purpose: Optional[str] = None
    session_reference: Optional[str] = None


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
_ACCOUNT_SECRET_FIELDS = ("session_state_encrypted",)


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
    return out


def _template_public(row: dict) -> dict:
    """A template as the client sees it — never its attachment's path."""
    out = _tag_utc(row)
    out["variables"] = template_svc.extract_variables(row.get("body") or "")
    out["has_attachment"] = bool(out.pop("attachment_path", None))
    return out


def _campaign_public(row: dict) -> dict:
    out = _tag_utc(row)
    total = int(out.get("total_targets") or 0)
    processed = int(out.get("processed_count") or 0)
    out["progress"] = round(processed / total, 4) if total else 0.0
    # The attachment's location on disk is nobody's business but the
    # driver's. The client only needs to know there is one and what it was
    # called; the bytes come from the endpoint, which checks ownership.
    out["has_attachment"] = bool(out.pop("attachment_path", None))
    return out


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

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

        database = await db.get_db()
        try:
            body = data.message_template
            template = None
            if data.template_id:
                template = await _own_template(database, data.template_id, user)
                body = body or template["body"]
            # Validated now so a broken template can't reach the worker.
            try:
                # A follow campaign sends nothing, so it needs no template
                # and must not be rejected for lacking one.
                if data.activity != ACTIVITY_FOLLOW:
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
                message_template=body,
                template_id=data.template_id,
                template_vars=template_svc.dump_vars(data.template_vars),
                platform=data.platform,
                activity=data.activity,
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

    @router.get("/campaigns/{campaign_id}/progress")
    async def campaign_progress(campaign_id: int, user: dict = Depends(get_current_user)):
        """Small payload for the dashboard's live poll."""
        database = await db.get_db()
        try:
            campaign = await _own_campaign(database, campaign_id, user)
            counts = await db.count_outreach_targets(database, campaign_id)
            totals = stats.totals_from_counts(counts)
            jobs = await db.get_outreach_jobs(database, campaign_id=campaign_id, limit=10)
            return {
                "status": campaign["status"],
                **totals,
                "target_counts": counts,
                "recent_jobs": [_tag_utc(dict(j)) for j in jobs],
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
            if data.message_template is not None:
                if campaign["status"] == CAMPAIGN_RUNNING:
                    raise HTTPException(
                        400, "Pause the campaign before editing its message"
                    )
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
                updates["activity"] = data.activity
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
    async def export_results(campaign_id: int, user: dict = Depends(get_current_user)):
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

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([
            "username", "profile_url", "status", "attempts",
            "sending_account", "last_attempt_at", "sent_at", "error_message",
        ])
        for row in rows:
            item = dict(row)
            writer.writerow([
                item.get("username"), item.get("profile_url"), item.get("status"),
                item.get("attempts"),
                accounts.get(item.get("assigned_account_id") or -1, ""),
                item.get("last_attempt_at") or "", item.get("sent_at") or "",
                (item.get("error_message") or "").replace("\n", " "),
            ])
        buffer.seek(0)
        filename = f"outreach-campaign-{campaign_id}.csv"
        return StreamingResponse(
            iter([buffer.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # --- controls --------------------------------------------------------

    async def _preflight(database, campaign: dict) -> list[str]:
        """Reasons this campaign cannot start. Empty list means go."""
        problems: list[str] = []
        try:
            template_svc.validate_template(campaign.get("message_template") or "")
        except template_svc.TemplateError as exc:
            problems.append(str(exc))
        counts = await db.count_outreach_targets(database, campaign["id"])
        if counts.get("queued", 0) + counts.get("paused", 0) == 0:
            problems.append("No queued targets — import a list first")
        if not await account_mgr.eligible_account_ids(database, campaign):
            problems.append(
                "No enabled sending account for this campaign — add one, or "
                "re-enable a paused account"
            )
        return problems

    @router.post("/campaigns/{campaign_id}/start")
    async def start_campaign(campaign_id: int, user: dict = Depends(get_current_user)):
        database = await db.get_db()
        try:
            campaign = await _own_campaign(database, campaign_id, user)
            problems = await _preflight(database, campaign)
            if problems:
                raise HTTPException(400, {"errors": problems})
            settings = await cfg.get_all(database)
            created = await job_queue.start_campaign(database, campaign, settings)
            await db.log_outreach_audit(
                database, AUDIT_CAMPAIGN_STARTED, "campaign", campaign_id,
                user_id=user["id"], detail=f"queued {created} job(s)",
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
            await db.log_outreach_audit(
                database, AUDIT_CAMPAIGN_RESUMED, "campaign", campaign_id,
                user_id=user["id"], detail=f"queued {created} job(s)",
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
            await _own_account(database, account_id, user)
            updates: dict[str, Any] = {}
            if data.name is not None:
                if not data.name.strip():
                    raise HTTPException(400, "Account name cannot be empty")
                updates["name"] = data.name.strip()
            if data.session_reference is not None:
                updates["session_reference"] = data.session_reference.strip() or None
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
                "Session encryption is not configured — set ICREATE_OUTREACH_SECRET "
                "(or ICREATE_JWT_SECRET) on the backend",
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
        account_id: int, user: dict = Depends(get_current_user)
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

        try:
            capture = session_capture.start(account)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return capture.to_dict()

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
                used = await discovery.visited_today(database, int(account["id"]))
                budgets.append({
                    "id": account["id"],
                    "name": account["name"],
                    "used_today": used,
                    "remaining_today": max(
                        int(settings["outreach_discovery_daily_cap"]) - used, 0
                    ),
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
        return {
            "available": reason is None,
            "unavailable_reason": reason,
            "busy": discovery.any_running(),
            "accounts": budgets,
            "daily_cap": int(settings["outreach_discovery_daily_cap"]),
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
            account = next(
                (a for a in accounts if a["id"] == data.account_id), accounts[0]
            )
            settings = await cfg.get_all(database)

            row = (await database.session.execute(
                text(
                    "INSERT INTO outreach_lead_searches "
                    "  (user_id, campaign_id, platform, niche, location, "
                    "   interests, wanted, include_commenters, include_likers, "
                    "   enrich_profiles, seed_accounts, account_id, status) "
                    "VALUES (:uid, :cid, :platform, :niche, :loc, :interests, "
                    "        :wanted, :commenters, :likers, :enrich, :seeds, "
                    "        :aid, :status) RETURNING id"
                ),
                {
                    "uid": user["id"], "cid": campaign_id, "platform": platform,
                    "niche": data.niche.strip(),
                    "loc": (data.location or "").strip() or None,
                    "interests": (data.interests or "").strip() or None,
                    "wanted": max(1, int(data.wanted or 50)),
                    "commenters": bool(data.include_commenters),
                    "likers": bool(data.include_likers),
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
        return {"ok": True, "was_running": discovery.cancel(search_id)}

    @router.get("/leads/searches/{search_id}/leads")
    async def list_leads(
        search_id: int, user: dict = Depends(get_current_user),
        limit: int = Query(500, ge=1, le=2000),
    ):
        """What a search found, best first. Unscored leads sort last."""
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
        limit: int = Query(1000, ge=1, le=5000),
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
