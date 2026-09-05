"""Shared vocabulary for the outreach pipeline.

These strings are duplicated in the CHECK constraints on the outreach
tables (`database.py`) and in the frontend status pills — change them in
all three places or not at all.
"""
from __future__ import annotations

# --- Campaign -------------------------------------------------------------
CAMPAIGN_DRAFT = "draft"
CAMPAIGN_RUNNING = "running"
CAMPAIGN_PAUSED = "paused"
CAMPAIGN_COMPLETED = "completed"
CAMPAIGN_STOPPED = "stopped"
CAMPAIGN_STATUSES = (
    CAMPAIGN_DRAFT, CAMPAIGN_RUNNING, CAMPAIGN_PAUSED,
    CAMPAIGN_COMPLETED, CAMPAIGN_STOPPED,
)

# --- Target ---------------------------------------------------------------
TARGET_QUEUED = "queued"
TARGET_PROCESSING = "processing"
TARGET_SENT = "sent"
TARGET_FAILED = "failed"
TARGET_SKIPPED = "skipped"
TARGET_PAUSED = "paused"
TARGET_STATUSES = (
    TARGET_QUEUED, TARGET_PROCESSING, TARGET_SENT,
    TARGET_FAILED, TARGET_SKIPPED, TARGET_PAUSED,
)

# --- Job ------------------------------------------------------------------
JOB_QUEUED = "queued"
JOB_PROCESSING = "processing"
JOB_SUCCEEDED = "succeeded"
JOB_FAILED = "failed"
JOB_CANCELLED = "cancelled"
JOB_STATUSES = (JOB_QUEUED, JOB_PROCESSING, JOB_SUCCEEDED, JOB_FAILED, JOB_CANCELLED)

# --- Sending account ------------------------------------------------------
ACCOUNT_IDLE = "idle"
ACCOUNT_ACTIVE = "active"
ACCOUNT_PAUSED = "paused"
ACCOUNT_ERROR = "error"
ACCOUNT_STATUSES = (ACCOUNT_IDLE, ACCOUNT_ACTIVE, ACCOUNT_PAUSED, ACCOUNT_ERROR)

# --- Driver result statuses ----------------------------------------------
# The browser layer returns one of these in `MessageResult.status`. The
# result processor maps them to retry / skip / pause-account decisions, so
# a new driver must reuse these rather than invent free-text codes.
RESULT_SENT = "sent"
RESULT_PROFILE_UNAVAILABLE = "profile_unavailable"
RESULT_MESSAGING_UNAVAILABLE = "messaging_unavailable"
RESULT_SESSION_EXPIRED = "session_expired"
RESULT_NAVIGATION_TIMEOUT = "navigation_timeout"
RESULT_UNEXPECTED_PAGE = "unexpected_page"
RESULT_BROWSER_ERROR = "browser_error"
RESULT_RATE_LIMITED = "rate_limited"
#: TikTok is showing a human-verification challenge (the slider puzzle)
#: instead of letting the account act. Nothing about the target is wrong, so
#: the target must stay retryable — recording it as "does not accept DMs"
#: skips a perfectly good profile for good. Only a person can clear this,
#: so the account is paused immediately rather than retried into the ground.
RESULT_CHALLENGE_REQUIRED = "challenge_required"
#: The browser went away underneath the job — almost always because the
#: worker was being shut down and systemd killed Chromium along with it.
#: Nothing was learned about the target or the account, so neither may be
#: blamed: not terminal, not an account fault, just run it again.
RESULT_ABORTED = "aborted"
RESULT_UNKNOWN = "unknown_error"
#: Raised above the driver: the message could not be rendered for this
#: target. Never retried — the same template and target produce the same
#: error every time.
RESULT_TEMPLATE_ERROR = "template_error"
#: The queue's own bookkeeping failed (DB error mid-result). Retryable.
RESULT_DB_ERROR = "database_error"

#: Permanent for this target — retrying cannot help, so the target is
#: marked `skipped` and the account is not blamed.
TERMINAL_RESULTS = frozenset({
    RESULT_PROFILE_UNAVAILABLE,
    RESULT_MESSAGING_UNAVAILABLE,
})

#: The account, not the target, is the problem. These count toward the
#: account's consecutive-error budget and pause it once exhausted.
ACCOUNT_FAULT_RESULTS = frozenset({
    RESULT_SESSION_EXPIRED,
    RESULT_RATE_LIMITED,
    RESULT_BROWSER_ERROR,
    RESULT_CHALLENGE_REQUIRED,
})

#: Failures no amount of retrying can clear — pause immediately rather than
#: burning the whole error budget on the same failure. An expired session
#: needs a fresh sign-in; a verification challenge needs a person to solve
#: the puzzle. Both are worse for being retried: every attempt in the
#: meantime fails, and each one is another challenged request from an
#: account TikTok is already suspicious of.
IMMEDIATE_ACCOUNT_PAUSE_RESULTS = frozenset({
    RESULT_SESSION_EXPIRED,
    RESULT_CHALLENGE_REQUIRED,
})

# --- Audit actions --------------------------------------------------------
AUDIT_CAMPAIGN_CREATED = "campaign.created"
AUDIT_CAMPAIGN_STARTED = "campaign.started"
AUDIT_CAMPAIGN_PAUSED = "campaign.paused"
AUDIT_CAMPAIGN_RESUMED = "campaign.resumed"
AUDIT_CAMPAIGN_STOPPED = "campaign.stopped"
AUDIT_CAMPAIGN_DELETED = "campaign.deleted"
AUDIT_CAMPAIGN_RETRY_FAILED = "campaign.retry_failed"
AUDIT_TARGETS_IMPORTED = "campaign.targets_imported"
AUDIT_ACCOUNT_CREATED = "account.created"
AUDIT_ACCOUNT_UPDATED = "account.updated"
AUDIT_ACCOUNT_ENABLED = "account.enabled"
AUDIT_ACCOUNT_DISABLED = "account.disabled"
AUDIT_ACCOUNT_DELETED = "account.deleted"
AUDIT_ACCOUNT_SESSION_SET = "account.session_set"
AUDIT_ACCOUNT_AUTO_PAUSED = "account.auto_paused"
AUDIT_ACCOUNT_ASSIGNED = "account.assigned"
AUDIT_ACCOUNT_UNASSIGNED = "account.unassigned"
AUDIT_WORKERS_TOGGLED = "workers.toggled"
