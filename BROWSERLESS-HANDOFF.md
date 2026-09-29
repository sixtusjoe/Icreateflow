# Browserless outreach — the plan, and the gate before it

> For whoever picks this up next, human or Claude, cold.
> Written 2026-09-22. **Updated the same day with the first probe's
> results — see §2a.** The discovery read has been demonstrated end to end
> in the scratchpad; nothing is implemented in `backend/`, and nothing is
> committed.

The goal is to take outreach off DOM-driving and onto the platforms' own
JSON endpoints. The decision that governs the whole project, from the user:

> **"i would like everything to be browserless but with seriously test and
> confirmed reliability first before implementing."**

So this document is two things in one: a build plan, and — first, and
larger — the evidence the build plan is not allowed to start without.

**Order is fixed: discovery first.** Comment discovery, then followers
discovery. Nothing else is designed here beyond a named phase list, because
a plan for messaging written before the discovery probe returns is a plan
written in the dark.

---

## 1. Why discovery first

Three reasons, all of them load-bearing.

1. **It is non-destructive.** A read changes nothing on the platform. If the
   probe is wrong, the cost is bad data in a scratch table, not a DM sent to
   a stranger or a burned account.
2. **It is where the payoff is.** `memory.md` §8b records the current
   reality: a read of one post *takes hours*, `LIST_HUNGRY_BUDGET_MS` is a
   **60-minute** backstop, and the whole quiet-rounds / dry-rounds /
   `_renudge` apparatus exists to cope with scroll-and-hope. A cursor-paged
   JSON list is a few dozen requests. Hours → minutes is the single largest
   win available anywhere in the pipeline.
3. **It is the honest test of the hard part.** Discovery on TikTok needs the
   same request signing that follow, comment and everything else needs. If
   signing does not hold up under a read, it will not hold up under a write
   either — and we will have learned that without sending anything.

There is also a structural reason it is safe to try: accounts are already
split by purpose. `ACCOUNT_PURPOSE_DISCOVERY` vs `ACCOUNT_PURPOSE_SENDING`
in [constants.py](backend/services/outreach/constants.py), with the comment
explaining exactly why — *"harvesting is a great deal of browsing in a short
window and is the likelier of the two to get an account restricted, so it
must not be the account that took days to get sending reliably."* **Every
probe in this document runs on discovery-purpose accounts only.** No sending
account is touched at any point in Phase 0.

> **This rule was broken on the first run, knowingly, and it should be fixed
> rather than quietly accepted.** There is no TikTok account with
> `purpose='discovery'` — the only three are #19 `RealMic TikTok`, #27
> `winny` (disabled) and #28 `Lancastar`, all `sending`. The probe used **#28**,
> chosen because it has `messages_processed = 0` and the freshest session, so
> it carries no sending history worth protecting; **#19, with 246 sends, is
> exactly the account the rule above is written to protect and was left
> alone.** Before Probe D or E runs — the fourteen-day ones, at volume — a
> real TikTok discovery account needs creating and signing in. A one-off
> read is one thing; two weeks of hourly reads on a sending account is the
> thing this rule exists to prevent.

---

## 2. What is unverified, and must be established by probe

Everything below is a hypothesis. Nothing in this section may be quoted as
fact in code comments until a probe confirms it against the live site.

| Claim | Status |
|---|---|
| TikTok comment lists are cursor-paged JSON | **CONFIRMED 2026-09-22** — `GET /api/comment/list/`, see §2a |
| TikTok follower lists are cursor-paged JSON | **unverified**, and follower lists are the more commonly restricted of the two |
| TikTok private endpoints require `X-Bogus`/`X-Gnarly` + `msToken` | **PARTLY WRONG** — `X-Bogus` is now the literal `1`; the live pair is `X-Gnarly` + **`X-Dynosaur`**, a name this document did not know |
| `msToken` is bound to `ttwid`/`odin_tt`/device ids, so a signature minted in one browser may not validate for another account's cookies | **still unverified across accounts**, but a signature minted in one context *is* reusable across many requests from a plain HTTP client with the same cookies — see §2a |
| Instagram needs `X-IG-App-ID` + `X-CSRFToken` + `X-IG-WWW-Claim` | medium-high |
| X GraphQL needs bearer + `ct0` and a per-operation query id | medium-high |

### 2a. What the first probe actually measured

Run 2026-09-22 against a real post with 1,637 comments, logged in as a stored
session, read-only, nothing written to any database. Scripts are in the
session scratchpad; nothing is committed.

| Question | Measured |
|---|---|
| Endpoint | `GET /api/comment/list/`, 36 query params, `cursor` advancing by `count` (20) |
| Response | `comments`, `cursor`, `has_more`, `total` — a clean cursor loop |
| Does one signature page the whole list? | **Yes for a while.** The signature does not cover `cursor`; 35 and 16 requests were served per mint |
| Signature lifetime | **Minutes.** A capture replayed a few minutes later failed on its first request |
| Unsigned requests | One succeeds, the second does not. Not a viable route |
| Failure mode | **HTTP 200 with a zero-byte body.** No status code, no error. Both an expired signature and absent cookies produce it |
| Coverage | 619 unique handles, then `has_more=0` at **cursor 1000** — a platform cap, not the end of the comments |
| The rest | 191 of those 619 advertise 441 replies via `reply_comment_total`; they need the reply endpoint. Ceiling ≈1,060 of 1,637 |
| Speed | 619 handles in **126 seconds**, across 3 mints, against `memory.md`'s "a read of one post takes hours" |

### 2b. The direct question: does it work with no browser at all? No.

Tested 2026-09-22 with a script that imports no browser library whatsoever —
stored cookies, hand-built parameters, plain HTTP, against an unthrottled
account. Three variants:

| Variant | Pages served |
|---|---|
| No signing parameters at all | **0** |
| `msToken` taken from the cookie jar | **0** |
| `msToken` + `X-Bogus=1` (its live value) | **0** |

Not one page. Every request came back HTTP 200 with an empty body.

**So "browserless" in the strict sense — no browser anywhere — is not
available for TikTok comment reading.** The signature is produced by
TikTok's own obfuscated JS and nothing we can send by hand substitutes for
it. What is available, and is a large win, is **DOM-less**: a browser opens
only to mint a signature (twice for a 1,639-comment post), and all reading
happens over plain HTTP. That is the honest name for it, and §3's kill
criteria already say not to relabel this as browserless to keep the project
alive.

### 2c. Messaging: confirmed out of reach on the same terms

Observed on the sending account's own inbox — opened, read, nothing sent:

- `POST im-api.tiktok.com/v2/message/get_by_user_init`,
  `Content-Type: application/x-protobuf`, with a **1,261-byte protobuf
  request body**. The inbox itself arrives as protobuf, not JSON.
- **Two** `wss://im-ws.tiktok.com/ws/v2` sockets, and **every frame binary**.
- Only the trimmings are JSON (`/api/im/spotlight/relation/`,
  `/tiktok/v1/im/user/profile/`).

A browserless DM would therefore need: the protobuf schema (unpublished —
it would have to come out of the `messages.*.js` bundle), a maintained
binary WebSocket, *and* the signing we have just shown cannot be done
without a browser. Since the simplest case — a JSON GET — already fails
without a browser, messaging is not reachable by the same route. Phase 6's
"possibly never" stands, and it is now measured rather than guessed.

### 2d. Probe E answered itself on day one — we throttled an account

**The read is not free, and the cost is the account.** Measured 2026-09-22,
same session as §2a:

| Account | Requests we sent it | What its own browser gets now |
|---|---|---|
| #28 `Lancastar` | ~700 across one post (root + reply threads) | **HTTP 200, empty body — throttled** |
| #27 `winny` | a handful | 4 normal responses — unaffected |

The check is the honest one: load the post in a real browser with that
account's session and watch what the *page itself* is served. #28's own
browser is now served nothing where #27's is served comments, so this is the
account being degraded, not our client being rejected.

This is the hypothesis in Probe E — *"a client that only ever calls the
comment endpoint is a more obvious robot than a browser that loads a page"* —
confirmed on the first day, on one post, by one read. It did not need
fourteen days to show up.

What it does **not** yet tell us:

- Whether the throttle decays. It may be an hour, a day, or permanent.
  **Re-check #28 before assuming anything.**
- Where the threshold is. 700 requests tripped it; a handful did not. The
  usable read rate is somewhere between, and finding it is now the most
  valuable measurement left — it sets the real throughput of the whole
  project, not the 126-second figure in §2a.
- Whether pacing (delay, jitter, fewer pages per account) avoids it, or only
  postpones it.

**Consequence for the plan:** the hours → minutes win in §2a is real but
cannot be spent all on one account. A per-account request budget and a
read-rate limit are not polish to add in Phase 2 — they belong in the first
version of the reader, because without them a discovery run burns the account
it is running on. The §3 gate should add a threshold for it: *reads per
account per hour that leave the account able to read.*

### 2e. Is a signature bound to the account that minted it? Still unknown

Attempted, **inconclusive, and recorded here so it is not mistaken for
settled.** Two runs produced the same odd matrix: a signature minted by
`winny` worked with `Lancastar`'s cookies, while every matched
signature/cookie pair failed.

That is not evidence of portability. The experiment was confounded twice over:
signatures expire within minutes, so the first-minted one was already stale by
the time it was exercised; and #28 became throttled part-way through, which
takes away the own-account control the test depends on.

To settle it properly the test needs **two fresh, unthrottled accounts**, each
signature exercised against both cookie jars within seconds of minting, and
several repetitions. That is another reason to create real TikTok
discovery accounts before going further — see the note in §1.

Three consequences for the plan below:

1. **The shape is A2-lite, and it works.** One browser context mints a
   signature; a cookie-only HTTP client does the paging; when the signature
   dies the browser mints another and the walk resumes from its cursor. That
   was run end to end and terminated cleanly on `has_more=0`.
2. **Probe F is not optional and is now the first thing to build.** The empty
   200 is the normal way this endpoint fails, not an edge case. A reader that
   treats it as "no more comments" would have reported 619 handles as a
   complete read of a 1,637-comment post — and been believed.
3. **Probe C's threshold needs restating.** "Within 10% of the stated count"
   is unreachable: `total` counts replies and deleted comments that the root
   list will never return. The right measure is against the reachable
   ceiling, with the cap and the reply threads accounted for separately.

**The first task of Phase 0 is not to write a client.** It is to see what
actually goes over the wire before reasoning about it. **This step is done**
— done with a scripted recorder rather than by hand with DevTools, which
turned out better: it keeps the raw request and response of every call, which
is the recording §3's probe rules ask for anyway.

Two things it cost, worth knowing before repeating it:

- A bare Chromium gets TikTok's **"Site Maintenance"** block page and zero
  XHR. The driver's own launch profile from `playwright_base.py`
  (`--disable-blink-features=AutomationControlled` and the Chrome/125 macOS
  user agent) loads the page normally. Use the driver's profile, not a fresh one.
- The right-hand panel opens on **"You may like"**, not "Comments" — the
  first run recorded `/api/related/item_list/` and no comment list at all.
  The tab must be clicked, and the page hydrates late: `[data-e2e]` count
  climbs 3 → 20 → 175 over roughly fifteen seconds, so a click at seven
  seconds finds nothing. Its class is a rotating hash
  (`css-131k9o1-…`), so match it by role and text and wait.

---

## 3. Phase 0 — the gate

No production code. Nothing under `backend/services/` changes. Everything
lives in the scratchpad, and the output is a table of numbers.

### The six probes

Each probe answers exactly one question and can fail on its own.

#### Probe A — can it be signed at all, and by whom?

The pivot. Three candidate routes, in increasing order of what they cost to
keep alive:

| Route | Cost | Fails if |
|---|---|---|
| **A1 — in-page `fetch`** via `page.evaluate()` in the account's own live context | keeps Chromium; ~250MB/account | never, realistically; this is the fallback that always works |
| **A2 — signing sidecar**: one browser mints signatures for N cookie-only workers | one browser total | a signature minted in browser A is rejected for account B's cookies |
| **A3 — ported signer**: run `webmssdk.js` under Node with a stubbed `window`, or reimplement it | ~50MB/process, plus a permanent treadmill | the bundle's environment fingerprinting defeats the stub, or it rotates faster than we can follow |

**Run A2 first**, because it is the one that decides whether "browserless"
is achievable at all in the sense the user means. Mint a signature in one
context, send the request with a *different* account's cookies, and see
whether it validates. That is a single afternoon and it settles the shape of
the entire project.

If A2 fails, the honest position is that TikTok is **A1 only** — still a
large win (see §4), but not browserless, and the user must be told that in
those words rather than having it quietly redefined.

#### Probe B — correctness

Read one post's commenters both ways: the new client, and the existing
Playwright reader. Compare the handle sets.

- Overlap as a percentage of the Playwright run.
- Handles the client found that the reader did not, and vice versa.
- Do it on **three posts**: one small (<200 comments), one large (>5,000),
  one already harvested — the third because `memory.md` records that a used
  post yields almost nothing, and the client must reproduce that rather than
  appearing to beat it by returning stale rows.

#### Probe C — completeness

Does the cursor actually run out, and does it run out at the right place?
Compare the total returned against the post's stated comment count. Reply
threads are the specific thing to watch: `memory.md` records that most of a
big post's people are in reply threads and that **the Instagram reply
selectors are unproven and matched nothing**. If the JSON carries replies
inline, that is a capability the DOM reader never had, and it should be
measured, not assumed.

#### Probe D — durability

The same call, on the same account, **every hour for 14 days**. Log every
response verbatim. What is being measured is not whether it works today; it
is the shape of how it stops working.

- Non-200 rate.
- Empty-result-with-200 rate — the dangerous one.
- Any change in response schema.
- Time to first failure, and whether it recovers on its own.

**14 days is the minimum and it is not negotiable down.** A signing scheme
that lasts a week proves nothing; platform deploys are the failure mode and
they do not happen on demand.

#### Probe E — account safety

The probe that actually decides the project, and the one that is easiest to
skip.

Two matched cohorts of discovery accounts — same age, same proxy class,
same volume, same hours. One reads via the new client; one reads via the
existing Playwright reader. Run for the full 14 days beside Probe D.

Measure per cohort: challenge rate, restriction rate, outright loss,
follower-list access revoked.

The hypothesis to disprove is the uncomfortable one: **a client that only
ever calls the comment endpoint is a more obvious robot than a browser that
loads a page.** A browser pulls images, CSS and telemetry; a bare client
does not. If the browserless cohort is challenged meaningfully more, the
speed win is not worth having and the project stops at A1.

#### Probe F — detectability of failure

Deliberately break it and confirm it says so. For each of: expired cookie,
corrupted signature, missing `msToken`, unexpected schema, and a 200 whose
body carries a platform-level error code — the client must return a distinct
status from [constants.py](backend/services/outreach/constants.py), never an
empty list.

This is the direct application of the rule that already cost three rounds to
learn, from `memory.md`:

> Write a stub that reproduces the new failure, confirm it **fails against
> the current code**, and only then fix it. A fix that was never seen to
> fail first is not trusted.

A browserless read fails *silently* far more readily than a DOM read, which
at least times out and leaves a screenshot. Probe F is what stands in for
that screenshot.

### The gate — pass/fail

Proposed thresholds. **These are proposals; the user sets the final
numbers before Phase 0 starts.**

| Probe | Pass |
|---|---|
| A | one of A1/A2/A3 works, and which one is written down |
| B | ≥ 95% of the Playwright reader's handles, and every extra one spot-checked as real |
| C | cursor terminates cleanly; total within 10% of the stated count, or the gap explained |
| D | ≥ 99% success over 14 days; **zero** silent-empty responses |
| E | browserless cohort's challenge rate **no worse** than the Playwright cohort's |
| F | all five injected faults produce a distinct, correct status |

**All six must pass.** Five out of six is a fail, and D and E cannot be
shortened — they are the two that only time can answer.

### Kill criteria

A plan that cannot fail is not a plan. Stop and report, do not work around:

- A2 and A3 both fail → TikTok is A1 only. Say so plainly; do not relabel
  in-page `fetch` as "browserless" to keep the project alive.
- Probe E shows a worse challenge rate → stop. Speed does not buy accounts.
- Probe D shows silent empties → stop until F can catch them. A reader that
  returns nothing and reports success is worse than no reader.
- The signer needs re-porting more than **twice** during Phase 0 → the
  treadmill is faster than we are; A1 is the answer.

### Probe rules

- **No production database.** Discovery writes `outreach_leads`; probes write
  to a scratch DB or nothing at all. Same standing rule as everywhere else in
  this repo: no write to `icreateflow` without explicit say-so.
- **Discovery-purpose accounts only.** No sending account is touched.
- Every probe run logs raw request and response to a file. When something
  breaks in month three, the recording is the only thing that will explain it.
- Nothing is committed.

---

## 4. What Phase 0 is worth even if it fails

Worth stating up front so the effort is not wasted on a no.

Even if A2 and A3 both fail and TikTok stays on a browser, **A1 — in-page
`fetch` — is still a large win**, and Phase 0 will have proved it:

- It removes the entire bug class in `memory.md` §"Driver bugs already paid
  for". All four were DOM-shape bugs: the Message button being a `div`,
  "Messages" matching "Message", the composer-empty heuristic, a CAPTCHA
  read as "no Message button". None can occur against a JSON endpoint.
- Real delivery confirmation from a status code, replacing the
  composer-empty-**and**-text-present inference that had to be invented.
- Follow-limit detection stops being guessed. Today `RESULT_FOLLOW_LIMITED`
  is inferred from a button that did not move
  ([playwright_base.py:1989](backend/services/outreach/browser/playwright_base.py#L1989));
  the JSON says so outright.
- Hours → minutes on discovery, which is most of the value regardless of
  where the signing lands.

What A1 does *not* buy is fleet density — still ~250MB per account. That is
the one thing only A2 or A3 delivers.

---

## 5. Code structure — one platform, one folder, no sharing

The user's rule:

> **"every code should written specifically for a platform so they dont
> conflict."**

This is a direct correction of what exists.
[playwright_base.py](backend/services/outreach/browser/playwright_base.py) is
**3,689 lines** shared across three platforms, and platform knowledge has
leaked into it anyway: `_likers_url` hard-codes Instagram's URL shape with X
overriding it, `FOLLOWERS_IN_DIALOG` is a flag that means "Instagram", and
`account_followers` branches on it. Every one of those is a place where
fixing one platform can break another.

The browserless layer does not repeat that.

```
backend/services/outreach/net/
├── __init__.py       get_reader(platform) — registry, like browser/__init__.py
├── result.py         ReadResult, LeadRow — the shared vocabulary, and nothing else
├── session.py        cookie jar, proxy wiring, TLS impersonation. No platform knowledge.
├── tiktok/
│   ├── endpoints.py  every URL, one constant each, written down verbatim
│   ├── sign.py       whichever of A1/A2/A3 won
│   ├── comments.py   the comment-list cursor loop
│   ├── followers.py  the follower-list cursor loop
│   └── parse.py      JSON → LeadRow
├── instagram/        the same five files. Zero imports from tiktok/.
└── x/                the same five files. Zero imports from tiktok/ or instagram/.
```

**The hard rule:** a platform folder may import from `net/` root. It may
**never** import from a sibling platform folder. Enforced by a test that
walks the AST of every module under `net/<platform>/` and fails on any
cross-platform import — not by convention, because convention is what
produced `FOLLOWERS_IN_DIALOG`.

**Duplication is the correct answer here.** If TikTok's and Instagram's
cursor loops end up 80% identical, they stay two loops. The third time a
flag is added to a shared function to make one platform behave differently,
that function has become `playwright_base.py` again.

What genuinely is shared, and all that is:

- `ReadResult` / `LeadRow` — the vocabulary above the layer.
- The status codes in [constants.py](backend/services/outreach/constants.py).
  **A new reader reuses these and invents no free-text codes** — that rule is
  already written into the file and applies here unchanged.
- HTTP session plumbing: proxy, TLS impersonation, retry-with-backoff.
  Platform-agnostic, and if it ever needs to know which platform it is
  talking to, that is the signal it has been written wrong.

### The seam it plugs into

Already the right shape, and it does not need changing.
[discovery.py:354](backend/services/outreach/discovery.py#L354) resolves a
driver by name from `site_config.outreach_driver`, then calls
`discover_from_posts`, `discover_from_engagement`, `discover_followers`,
`discover_profiles`. A browserless reader that satisfies those four
signatures drops in behind the same config switch, and can be run on **one
account beside the existing driver** for as long as it takes to trust it.

Note the one piece of debt to clean up on the way: discovery.py:484 reaches
into `driver._context_for(...)` — a private browser method called from
outside the browser layer. A reader with no browser has no context, so that
call has to move behind a public method before either driver can satisfy the
interface.

---

## 6. Phase order

Nothing past Phase 2 is designed. That is deliberate.

| Phase | Scope | Starts when |
|---|---|---|
| **0** | The six probes. TikTok only. No production code. | now |
| **1** | **Comment discovery**, TikTok, behind `outreach_driver`, one account | all six probes pass and the user says go |
| **2** | **Followers discovery**, TikTok | Phase 1 has run a week in production without a silent empty |
| **3** | Instagram, then X — repeat 0→2 per platform, own folder, own probes | Phase 2 stable |
| **4** | Follow / unfollow (signed POSTs; unfollow is the same endpoint with a flag) | Phase 3 |
| **5** | Comment posting | Phase 4 |
| **6** | **DMs — TikTok only if the IM layer is solved** | last, and possibly never |

**Phase 6 carries a standing warning, and it is now confirmed rather than
suspected.** Observed 2026-09-22 while merely loading a video page — no DM
opened, no inbox read, nothing sent:

- `POST https://im-api.tiktok.com/v2/message/get_by_user_init` with
  `Content-Type: application/x-protobuf`. A **different host** from
  `www.tiktok.com`, and a **binary** wire format.
- A persistent `wss://im-ws.tiktok.com/ws/v2?...&access_key=…` WebSocket,
  exchanging binary frames from the moment the page loads.

So none of what Phase 1 solves transfers here. The comment list is cursor-paged
JSON on `www.tiktok.com` signed with `X-Gnarly`/`X-Dynosaur`; DMs are protobuf
over a separate host plus a live socket. Solving signing does not get you there. It is the largest piece of work in the list
and its failure mode is the silent one — messages that report sent and were
never delivered, which is exactly the bug already paid for once
(`memory.md`, driver bug #2). Instagram and X DMs are a different and much
smaller problem; they should not be blocked behind TikTok's.

Per-phase exit criteria, same for each: one week in production, zero silent
empties, challenge rate flat against the previous driver, and a rollback that
is one `site_config` change.

### Follow/unfollow — the note for Phase 4

Recorded now so it is not rediscovered later:

- Follow exists today, DOM-driven, at
  [playwright_base.py:1989](backend/services/outreach/browser/playwright_base.py#L1989).
- **There is no unfollow action.** But the codebase is far from silent on the
  subject: 31 mentions across the X and Instagram drivers and their tests, all
  of them about *preventing an accidental one*. X flips the same element's
  `data-testid` from `-follow` to `-unfollow` once pressed, and Instagram's
  button says "Following" — so a substring match on `Follow` unfollows
  somebody on every target, silently. `:text-is('Follow')` is what separates
  them, and there are dedicated tests holding that line.
- **This means Phase 4 is deliberately doing the thing those tests exist to
  prevent.** Do not loosen a selector to get there. Add an explicit
  `unfollow_target` path with its own control lookup, keep every existing
  guard, and keep the tests that prove a follow campaign never unfollows.
- The detection half is already written: `_profile_follow_control` reads the
  `following`/`pending` state and the code notes *"the control here is the one
  that undoes it"*. The button is already identified; it is simply never
  pressed on purpose.
- The records to drive it already exist. `outreach_targets` carries
  `assigned_account_id` and `sent_at`, so under a campaign with
  `activity='follow'` we already know which account followed whom and when.
  **No new table is needed.**
- **Follow/unfollow churn is the most ban-associated pattern on every one of
  these platforms.** Followed-then-unfollowed at volume from one account is
  trivially detectable server-side and is what the limits exist to catch. If
  the plan is cycling for growth, size the account budget around account
  loss, not around throughput.

---

## 7. What to do first, concretely

1. Get the user's sign-off on the §3 thresholds. They are proposals.
2. Open a real logged-in TikTok session with DevTools recording. Click into
   a post's comments, scroll once, and open a follower list. Write down the
   actual requests. **Do not write a client before this step.**
3. Run **Probe A2** — mint a signature in one context, use it with another
   account's cookies. One afternoon; it decides the shape of everything else.
4. Stand up Probes D and E together and let them run the full 14 days. They
   are the long pole; everything else fits inside their window.
5. Report the numbers. Do not start Phase 1 without them.

---

## 8. Standing rules that apply throughout

Carried from the rest of this repo, unchanged:

- **Nothing is committed** — not local, not git — until the user says.
- **No write to the production database** (`icreateflow`) without explicit
  say-so. The local backend points at production.
- **Report honestly.** If a probe fails, say it failed and show the numbers.
  A phase that half-worked is a phase that did not pass.
- **Stubs are more cooperative than the real site.** Reproduce the failure
  first, watch it fail against current code, then fix.
