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
#: What a campaign does to each target. Messaging is the original and
#: stays the default; following is its own campaign — warming an account,
#: or building an audience before a word is written.
ACTIVITY_MESSAGE = "message"
ACTIVITY_FOLLOW = "follow"
#: Many accounts leaving a comment each on one video. The campaign holds
#: the video, not a list of people, so its targets are comment slots — one
#: row per comment the operator asked for.
ACTIVITY_COMMENT = "comment"
#: Undo a follow. Only ever presses a control that is in a followed state,
#: so a profile that is not followed is left alone — an unfollow campaign
#: can never follow anybody.
ACTIVITY_UNFOLLOW = "unfollow"
CAMPAIGN_ACTIVITIES = (ACTIVITY_MESSAGE, ACTIVITY_FOLLOW, ACTIVITY_COMMENT,
                       ACTIVITY_UNFOLLOW)
#: Where unfollowing is built. Anything else is refused at creation rather
#: than failing every target one at a time.
UNFOLLOW_PLATFORMS = ("tiktok", "instagram")

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

#: What an account is for. Kept apart deliberately: harvesting is a great
#: deal of browsing in a short window and is the likelier of the two to get
#: an account restricted, so it must not be the account that took days to
#: get sending reliably.
ACCOUNT_PURPOSE_SENDING = "sending"
ACCOUNT_PURPOSE_DISCOVERY = "discovery"
ACCOUNT_PURPOSES = (ACCOUNT_PURPOSE_SENDING, ACCOUNT_PURPOSE_DISCOVERY)

# How an account does its work: signed in on the server's browser, or on
# the user's own phone through the ICREATEFLOW app (services/outreach/
# companion.py). A phone account has no browser session to fall back on,
# so it only takes the activities the phone app can do.
ACCOUNT_VIA_BROWSER = "browser"
ACCOUNT_VIA_PHONE = "phone"
ACCOUNT_VIAS = (ACCOUNT_VIA_BROWSER, ACCOUNT_VIA_PHONE)
#: What the phone app does today, and on which platform.
PHONE_ACTIVITIES = (ACTIVITY_FOLLOW, ACTIVITY_MESSAGE, ACTIVITY_UNFOLLOW)
PHONE_PLATFORMS = ("tiktok",)

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
#: The video will not take a comment: the creator turned comments off, or
#: restricted them to people they follow. Every slot on that campaign hits
#: the same wall, so retrying is pointless and the target is done with.
RESULT_COMMENTS_CLOSED = "comments_closed"
#: Everyone reachable under the video has already been replied to. Not a
#: fault: the campaign asked for more replies than the video has people,
#: and answering someone twice is worse than leaving a slot unused.
RESULT_NO_ONE_LEFT = "no_one_left"
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
#: TikTok accepted the message into the thread and then refused to deliver
#: it — "may be in violation of our Community Guidelines, and has not been
#: sent to protect our community", shown beside the message with an error
#: marker. Nothing was delivered, so this must never be reported as sent.
#: The target has just been followed and the message is deliberately held
#: back. Not a failure — the job is requeued to run after the wait, which
#: is the point: a follow and a DM in the same second is not what a person
#: looks like, and TikTok gates who may message whom on the follow
#: relationship in the first place.
RESULT_FOLLOW_PENDING = "follow_pending"
#: The platform is still showing a Follow button and quietly ignoring
#: presses. Not a fault of ours and not of the target — the account
#: has followed too many people too quickly and must wait.
RESULT_FOLLOW_LIMITED = "follow_limited"
#: The follow campaign's work was already done — the profile was followed
#: before we got there, and the control on the page is the one that would
#: *undo* it. A success, because the campaign wanted this account followed
#: and it is, but deliberately not `sent`: nothing was pressed and the
#: account's following count does not move.
#:
#: Kept apart because the two were indistinguishable in the record, and the
#: difference is the only way to answer "are the follows actually landing".
#: A run reporting 56 sent while the account's following count rose by 16
#: is not a broken follow — it is 40 profiles that were already followed,
#: and there was no way to see that from the database.
#: A read came back HTTP 200 with an empty body.
#:
#: The normal way TikTok's JSON endpoints fail. There is no status code in
#: it, no error text, nothing — an expired signature and absent cookies both
#: produce it, and so does a throttled account. Measured 2026-09-22: a
#: reader that treated it as "no more results" reported 619 handles as a
#: complete read of a 1,637-comment post, and would have been believed.
#:
#: It exists so that no reader can ever return an empty list for it.
RESULT_EMPTY_RESPONSE = "empty_response"
RESULT_ALREADY_FOLLOWING = "already_following"
#: Private account: the follow was requested and a person has to accept it.
#: Also a success — there is nothing further to press — but again not a
#: follow: the count does not move until they accept, and it may never.
RESULT_FOLLOW_REQUESTED = "follow_requested"
#: An unfollow campaign found the profile not followed — nothing to undo,
#: nothing pressed. A success, kept apart from `sent` (an unfollow that
#: happened) for the same reason `already_following` is.
RESULT_NOT_FOLLOWING = "not_following"
#: An unfollow campaign met someone none of its accounts followed through
#: an ICREATEFLOW follow campaign — a friend, a follow made by hand. Left
#: alone, nothing pressed: unfollow undoes only our own "Followed" results.
RESULT_NOT_OUR_FOLLOW = "not_our_follow"
#: The platform accepted the follow, said it succeeded, and did not keep it.
#:
#: Measured 2026-09-23 on TikTok, two accounts, three attempts, none stuck:
#: `POST /api/commit/follow/user/` answered HTTP 200 with
#: `{"status_code": 0, "follow_status": 1, "status_msg": ""}` — an explicit
#: success — and the button turned to "Following". Reload the profile and
#: it reads "Follow" again. The follow was never recorded.
#:
#: This is why the driver reloads instead of trusting the button, and why
#: doing the follow as a plain JSON call would be a step backwards: the
#: call is the same one the button makes, and its success field is the part
#: that lies. Only re-reading the profile tells the truth.
RESULT_FOLLOW_DISCARDED = "follow_discarded"
RESULT_MESSAGE_REFUSED = "message_refused"
#: The phone that does this account's app-side work cannot be used: not
#: plugged in, locked, TikTok not installed, or signed in as somebody else.
#: Only a person can fix any of those, and the last one is the dangerous
#: one — a phone signed in to the wrong account would follow from it — so
#: the account is paused at once rather than retried.
RESULT_DEVICE_UNAVAILABLE = "device_unavailable"
RESULT_ABORTED = "aborted"
RESULT_UNKNOWN = "unknown_error"
#: The phone took a message and never said what happened — it may have
#: gone out. Never retried: a missed message is better than a second one.
RESULT_OUTCOME_UNKNOWN = "outcome_unknown"
#: Raised above the driver: the message could not be rendered for this
#: target. Never retried — the same template and target produce the same
#: error every time.
RESULT_TEMPLATE_ERROR = "template_error"
#: The queue's own bookkeeping failed (DB error mid-result). Retryable.
RESULT_DB_ERROR = "database_error"

#: The platform has told us this account has done as much as it is allowed
#: for now. Not a fault of the account, the target, or us — a clock.
#:
#: These used to be plain account faults, which auto-paused the *account*
#: after five of them. That is the wrong unit twice over: the account is
#: healthy and stopping it stops every other campaign it serves, and a
#: paused account needs a person to notice and un-pause it, so a limit that
#: clears by itself in hours cost a day. The campaign stands down instead,
#: with a deadline it resumes itself on.
LIMIT_RESULTS = frozenset({
    RESULT_FOLLOW_LIMITED,
    RESULT_RATE_LIMITED,
    # A discarded follow is the same kind of thing: the account is not
    # broken and the target is fine, the platform is simply not letting
    # this through right now. Standing the campaign down beats spending a
    # thousand targets on follows that evaporate.
    RESULT_FOLLOW_DISCARDED,
})

#: Permanent for this target — retrying cannot help, so the target is
#: marked `skipped` and the account is not blamed.
#:
#: Only verdicts reached by *seeing* something belong here. A profile that
#: renders "Couldn't find this account" really is gone, and no number of
#: retries changes that.
#:
#: `messaging_unavailable` is deliberately NOT in this set, though it reads
#: like it belongs. It is inferred from the *absence* of a Message button,
#: and absence turned out to have many causes that have nothing to do with
#: the target: a verification puzzle covering the profile, a browser closed
#: mid-job by a worker restart, and TikTok serving its own "Something went
#: wrong" page. Each one skipped a live, reachable target permanently, with
#: no way back short of editing the database. Retrying a profile that
#: genuinely has DMs closed costs a handful of attempts; the other mistake
#: costs the target for good.
TERMINAL_RESULTS = frozenset({
    RESULT_PROFILE_UNAVAILABLE,
    RESULT_NOT_OUR_FOLLOW,
    RESULT_COMMENTS_CLOSED,
    RESULT_NO_ONE_LEFT,
})

#: The account, not the target, is the problem. These count toward the
#: account's consecutive-error budget and pause it once exhausted.
ACCOUNT_FAULT_RESULTS = frozenset({
    RESULT_SESSION_EXPIRED,
    RESULT_BROWSER_ERROR,
    RESULT_CHALLENGE_REQUIRED,
    RESULT_DEVICE_UNAVAILABLE,
})
# `rate_limited` and `follow_limited` are deliberately absent: see
# LIMIT_RESULTS above. They pause the campaign, not the account.

#: Failures no amount of retrying can clear. They no longer pause the
#: account (see PHONE_RETRY_RESULTS / CAMPAIGN_ATTENTION_RESULTS); the name
#: survives because the runner still rebuilds the browser after them.
IMMEDIATE_ACCOUNT_PAUSE_RESULTS = frozenset({
    RESULT_SESSION_EXPIRED,
    RESULT_CHALLENGE_REQUIRED,
    RESULT_DEVICE_UNAVAILABLE,
})

#: **Nothing pauses an account.** Operator's rule (2026-09-26, said twice):
#: a paused account silently stopped every campaign it served, and the
#: phone's follow run kept dying on one-off hiccups. Problems stop the
#: *campaign* that met them, with the reason on it, and the account goes
#: on serving everything else.
#:
#: The phone (either route) couldn't do it this time: TikTok slow to come
#: to the front, a profile that didn't load, the phone not asking for work.
#: Usually gone a minute later — the job is held and retried, and only a
#: streak of them gives the campaign a short break (runner.py).
PHONE_RETRY_RESULTS = frozenset({
    RESULT_DEVICE_UNAVAILABLE,
})

#: Needs a person: a sign-in that expired, a puzzle to solve. Retrying only
#: fails again (and a puzzle retried is another suspicious request), so the
#: campaign pauses with no clock and says which account needs what.
CAMPAIGN_ATTENTION_RESULTS = frozenset({
    RESULT_SESSION_EXPIRED,
    RESULT_CHALLENGE_REQUIRED,
})

#: The platform refused the *message*, so the campaign stops — not the
#: account, and not on a clock.
#:
#: This used to pause the account, on the theory that a refusal speaks to
#: the account's standing. In practice it speaks to the words: TikTok's
#: "may be in violation of our Community Guidelines" notice is about what
#: was said, the same account sends other campaigns fine, and pausing it
#: stopped every one of them over one campaign's text. A countdown is no
#: use either — the same text is refused again when it runs out. So the
#: campaign stays paused, with the platform's reason on it, until its
#: message is changed; `routers/outreach.py:_preflight` holds it to that.
CAMPAIGN_STOP_RESULTS = frozenset({
    RESULT_MESSAGE_REFUSED,
})

#: Retrying these is pointless — the same input produces the same outcome.
#: A refused message will be refused again word for word, and every attempt
#: is another flagged message from an account the platform has already told
#: us is at risk.
NEVER_RETRY_RESULTS = frozenset({
    RESULT_TEMPLATE_ERROR,
    RESULT_OUTCOME_UNKNOWN,
    RESULT_MESSAGE_REFUSED,
    RESULT_COMMENTS_CLOSED,
    RESULT_NO_ONE_LEFT,
})

# --- Audit actions --------------------------------------------------------
AUDIT_CAMPAIGN_CREATED = "campaign.created"
AUDIT_CAMPAIGN_STARTED = "campaign.started"
AUDIT_CAMPAIGN_PAUSED = "campaign.paused"
AUDIT_CAMPAIGN_RESUMED = "campaign.resumed"
#: Stood down because the platform said it had hit a limit, and picked up
#: again when the cooldown expired. Separate from the operator's own
#: pause/resume so a run's history shows which were decisions and which
#: were the platform.
AUDIT_CAMPAIGN_LIMITED = "campaign.limited"
AUDIT_CAMPAIGN_LIMIT_CLEARED = "campaign.limit_cleared"
#: Stood down because the platform refused the message itself. No clock:
#: it waits for the message to change.
AUDIT_CAMPAIGN_MESSAGE_REFUSED = "campaign.message_refused"
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
