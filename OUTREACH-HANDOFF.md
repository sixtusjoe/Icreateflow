# Outreach — handoff notes

Written 2026-09-04, for a Claude Code session picking this up on the Mac.

The feature is **built, tested, deployed and live**. What is *not* finished is
making it actually deliver a DM against real TikTok. Three separate browser
bugs have been found and fixed that way; the third fix has not yet been
confirmed against the live site. That is the open thread.

Read these first, in this order:

1. `memory.md` — every outreach bullet. These are hard-won and each one cost a
   failed campaign to learn. Do not re-derive them.
2. `README.md` § *Outreach — How it works* — the architecture and the CLI.
3. `deploy/DEPLOY.md` — the server, the units, the deploy path.

---

## You can do things the previous session could not

That session ran in a cloud container: no SSH key, port 22 blocked, no access
to the Mac or the server. Everything on the box had to be relayed through the
user copy-pasting terminal output, which is slow and lossy.

You live on the Mac. You can `ssh root@95.111.228.80` directly. **Use it.**
Read the worker logs yourself, pull the debug screenshots yourself, run the
watch script yourself. Do not make the user be your terminal.

```bash
ssh root@95.111.228.80 "journalctl -u 'icreateflow-outreach-worker@*' -n 200 --no-pager"
ssh root@95.111.228.80 'ls -t /srv/icreateflow/backend/outreach-debug | head'
scp root@95.111.228.80:/srv/icreateflow/backend/outreach-debug/<file>.png /tmp/
```

Those screenshots are the fastest way to tell a changed selector from a
blocked account. Look at them.

---

## State right now

- Live at `icreateflow.com/outreach`. Backend, frontend, workers all running.
- Sending account 1 (`sixtusjoe`) is signed in — session captured **on the
  server** and encrypted into the DB. It has **4 consecutive errors**, and
  `outreach_account_error_threshold` is **5**. One more failure auto-pauses
  it. If it pauses: `/outreach/accounts` → Resume
  (`POST /api/outreach/accounts/{id}/resume`).
- Last campaign run: job #4 came back `unexpected_page`, target still
  `queued`. That failure is what the newest fix addresses.
- Latest commits on `main`: `3c26dc3` (the driver fix), `cbbc728` (ship.sh
  pulls before pushing).

### Do this first

```bash
cd ~/Desktop/zagged && git pull && bash deploy/ship.sh
```

Then on the campaign page hit **Retry failed**, and watch it happen:

```bash
bash deploy/outreach-watch-mac.sh
```

That runs one real send with the browser visible over VNC, with the
background workers paused so they cannot steal the job. `bash
deploy/outreach-watch-mac.sh mock` rehearses without sending.

**Then verify the outcome honestly.** "Campaign completed" has already lied
once (see bug 2 below). The only proof is the message appearing in the
receiving account's inbox.

---

## The three bugs already fixed — do not re-introduce them

Each was invisible to the test suite and only appeared against live TikTok.

1. **The Message button is a `div`, not a `<button>`.** `button:has-text(…)`
   never matched it, so real profiles were skipped as "does not accept DMs".
   Selectors are now tiered: `data-e2e` hooks first, generic role/text second.
   Tiers matter because `_first_visible` *races* the selectors inside a tier —
   a loose one can beat the real control.

2. **"Is the message text on the page?" is not delivery confirmation.** The
   composer is part of the page. A send that silently did nothing left the
   text in the input, the check found it, and the campaign reported *sent*
   having sent nothing. Confirmation is now: composer **empty** *and* the text
   still on the page. Never weaken this.

3. **"Messages" contains "Message".** TikTok's left nav has a *Messages*
   entry; the loose tier matched it and, because the selectors race, it beat a
   profile button that rendered a beat late. The click navigated to the inbox
   — surfacing as "composer never opened" on what still looked like the
   profile URL. The generic tier now uses `:text-is` (exact). Separately,
   clicking Message can legitimately hand off to the messages app, so the
   driver will open the target's own conversation row — **matched exactly,
   never fuzzily**, because those rows are other people's chats and a
   near-match would DM a stranger.

Bug 3's fix is the unverified one.

---

## How to debug the next failure

The driver is instrumented for exactly this. When something misses it logs
`page offers: [...]` — every clickable element as `data-e2e|label`. That list
answers "what is actually on the page", which is the only useful question.
It is what identified bug 3: `inbox-title|…` and `All activity / Likes /
Mentions and tags` in the list meant the browser was standing in the inbox.

**The rule, which cost three rounds to learn:** the stubs were more
cooperative than the real site — they cleared their composer, rendered
instantly, and used the tags we expected. So:

> Write a stub that reproduces the new failure. Confirm it **fails against
> the current code**. Only then fix it.

Every driver stub now has a deliberately-broken twin: `/silentfail`,
`/swallowed`, `/renamed`, `/divbutton`, `/navmessages`, `/inboxmiss`.
A fix that was never seen to fail first is not trusted.

```bash
cd backend
python -m pytest tests/test_outreach_playwright_driver.py -q     # 24 tests, ~75s
```

Requires `playwright==1.56.0` exactly — Playwright only launches the Chromium
build it shipped with, and a version drift shows up as every test *skipping*,
not failing.

---

## Environment facts worth knowing

- Server `root@95.111.228.80`; app at `/srv/icreateflow`, source at
  `/srv/icreateflow/src`, venv at `/srv/icreateflow/venv`.
- Units: `icreateflow-backend`, `icreateflow-frontend`,
  `icreateflow-outreach-worker@N` (template unit, one per worker).
- Playwright browsers at `/srv/icreateflow/pw-browsers` —
  **not** root's `~/.cache`; the workers run as `icreateflow` and cannot read
  root's cache.
- Secrets live in `/srv/icreateflow/backend/.env` (`ICREATE_DB_DSN`,
  `ICREATE_JWT_SECRET`, `ICREATE_OUTREACH_SECRET`). Never print them, never
  commit them, never put them on a command line where `ps` can see them.
- `ICREATE_OUTREACH_SECRET` encrypts the stored browser sessions. **If it is
  lost or changed, every stored session becomes undecryptable** and all
  accounts have to be signed in again.

Driver timing knobs, all overridable by env var without a code change:
`ICREATE_OUTREACH_PROFILE_READY_MS` (12s), `MESSAGE_BUTTON_MS` (15s),
`COMPOSER_MS` (15s), `CLICK_MS` (10s), `TIMEOUT_MS` (30s),
`HEADLESS` (`0` shows the browser), `DEBUG_DIR`.

Everything else is tunable from **`/admin` → Outreach** with no deploy —
retry limit, concurrency, send interval, account error threshold, lease
duration, and the driver itself (`mock` vs `playwright_tiktok`). Defaults and
bounds are in `backend/services/outreach/config.py`. A worker picks up a
changed setting on its next tick.

---

## Result vocabulary

The driver returns one of these, and the queue decides what it means. A new
driver must reuse them rather than invent free text
(`backend/services/outreach/constants.py`):

| result | queue's decision |
|---|---|
| `sent` | target sent |
| `profile_unavailable`, `messaging_unavailable` | **terminal for the target** — skipped, account not blamed |
| `session_expired`, `rate_limited`, `browser_error` | **account's fault** — counts toward its error budget, pauses it when exhausted |
| `navigation_timeout`, `unexpected_page`, `unknown_error` | retryable, up to the retry limit |
| `template_error` | never retried — same input, same failure |

`session_expired` pauses the account immediately rather than burning the
whole budget on the identical failure.

---

## Open items

- **Unverified:** whether the inbox/nav fix actually works against live
  TikTok. This is the next thing to establish.
- **Offered, never answered:** `outreach-watch-mac.sh` takes *the next queued
  job*, not one picked from the list. A per-target "watch this one" would need
  a UI button and an API endpoint. The user was offered this and has not said
  yes — don't build it unasked.
- **Deliberately skipped:** the bare-glyph icon treatment (no tile
  backgrounds, theme-aware) was applied across the dashboard but not to the
  public landing page, `frontend/src/app/page.tsx`.

---

## Constraints that must hold

These are the user's, stated up front, and they are not negotiable:

- No raw passwords or plaintext credentials, ever. The operator signs in by
  hand; there is no password field in the driver by design.
- Never expose account credentials or session state in an API response.
  `_account_public()` strips `session_state_encrypted` and exposes only
  `has_session: bool` — keep it that way.
- Sessions are encrypted at rest (Fernet, `ICREATE_OUTREACH_SECRET`).
- Authorization checks on every campaign and account endpoint.
- Validate every imported URL.
- Audit-log campaign and account actions (`outreach_audit_logs`).

## Working style the user asked for

Short answers. One command, not three terminals. They have said twice that
long explanations lose them — so lead with the command to run, and keep the
reasoning to a line or two unless asked. Do not narrate what you are about to
do at length; do it, then say what happened.
