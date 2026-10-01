# Design handoff — the frontend redesign

> For whoever picks up the redesign next, human or Claude, cold.
> Written 2026-09-22. Branch `claude/previous-session-review-22f17d`.
> **Everything described here is uncommitted working tree.** 26 modified files,
> 31 new ones, nothing staged, nothing pushed — by standing instruction.

This is deliberately a *third* doc, and the repo normally keeps two
(`README.md`, `memory.md`). The last handoff file was deleted in `2c0af99`
for drifting into a second copy of `memory.md`, so this one stays off that
ground: it records **how the frontend is being designed** and **where the
redesign stopped**, which neither of the other two covers at all. When the
redesign lands, the durable parts (the kit rules, the write-guard harness)
fold into `memory.md` and this file goes the same way the last one did.

---

## 1. Where we stopped

The redesign has converted the whole user-facing app except three pages, and
has just opened a second area — admin — with five of its screens built.

**Last three pieces of work, in order:**

1. **Wired the admin area.** Five pages (Overview, Users, User detail,
   Approvals, Assistant inbox) plus a dedicated admin rail, moved off the
   previews and into the real app. The old 13-tab admin page was not thrown
   away — it moved to `/admin/tools` and is still reachable from the rail.
2. **Removed the admin leak from the user pages.** `/help`, `/settings` and
   `/schedule` each printed an admin-only fault ("the public address is
   unset") with a link to `/admin`. All gone; sweep is clean.
3. **Fixed card-row alignment** across every route. Cards sharing a row now
   end level. Three rows were deliberately left ragged — see §6.

**Verified at the stopping point:** `tsc --noEmit` clean; `eslint src/app
src/components` clean on every touched file (pre-existing errors remain in
`admin/tools` and the clipping pages, which the redesign has not reached);
the alignment sweep and the admin-leak sweep both green.

**Next in the queue** is the user's call, not ours — the rule is one page at
a time with their verification between each (§2). §9 lists the candidates.

---

## 2. How the design is being done — the process

This is the part that matters most, because it is the part that has been
enforced hardest.

### The rules, from the user, standing

These are not preferences. Each one was stated directly and several were
re-stated after being broken.

| Rule | Why it exists |
|---|---|
| **Nothing is committed** — not to local, not to git | The user reviews first |
| **Do not touch the logo** | Stated flatly, twice. One change made at the owner's request (2026-10-01): the tile is near-black in both themes, no longer white in dark |
| **One page at a time, with user verification between each** | Nothing moves on until they have looked at the last thing |
| **Design a preview first, then wire it** — *"this is the main reason why we design before wiring!!"* | A wired page is expensive to argue with; an HTML preview is cheap |
| **When wiring a preview: "copy all the test pages as it is and implement it… check every single line of change we did on the test"** | The preview is the spec, not a mood board |
| **A redesigned page has no search bar, theme icon, bell icon or profile icon** | Those four were chrome nobody used |
| **Never write to the production database without explicit say-so** | The local backend points at production — see §8. This is the one that can do real damage |
| **Admin content is exclusive to admin** | A user must never see an admin-only fault, an admin link, or an admin endpoint call |
| **"we should still make it possible to delete anyone. you cant tell me i cant delete someone because they have active campaign."** | Ruled after the delete endpoint refused on an active campaign |
| **"for the Assistant inbox. both Ai and real human can reply. but the Ai should reply first."** | The hand-over model for `/admin/assistant` |

### The loop, per page

1. **Read the existing page end to end** — including the API calls it makes
   and what each one can actually return. The redesign is not allowed to
   invent capability.
2. **Build a static HTML preview** in the scratchpad and show it. Iterate on
   the preview, not the app.
3. **User verifies.** Only then wire.
4. **Wire it line by line against the preview.** Every divergence is a
   defect, not a judgement call.
5. **Verify live with Playwright** against `localhost:3000`, writes blocked
   (§8). Measure, do not trust the screenshot — full-page screenshots
   mis-render `position: fixed` sidebars, so geometry comes from
   `bounding_box()`.
6. **Lint and typecheck** before reporting (§7 lists the rules that bite).
7. **Report and stop.** Wait.

### The honesty rule

The design's strongest constraint: **a screen may not imply a capability the
backend does not have, and may not quietly omit one it cannot do.**

- A card whose figures are invented carries a `SampleBanner` naming exactly
  what is missing ("there is no subscriptions table, no payment provider and
  no AI usage log").
- A control drawn for a thing with no route behind it carries a `NoEndpoint`
  pill (`no endpoint`, or `user-scoped` when the route exists but is gated
  to the caller's own account).
- Every percentage names its denominator.

Both helpers are in `frontend/src/components/admin/ui.tsx`, with the
reasoning in the file's docstring: *"a screen that quietly omits what it
cannot do teaches you it cannot be done, and a screen that pretends is
worse."*

### The comment rule

Pages and shared components carry a **docstring that says why**, not what.
`frontend/src/app/help/page.tsx` is the model: it explains that the page had
never existed, that every card on it had to come from somewhere real, and
what was removed from it and where that thing went instead. When you change
one of these, update its docstring in the same edit — the docstrings are the
design record, and several of them explain decisions that will otherwise be
re-litigated.

---

## 3. The design system — tokens

All tokens live in `frontend/src/app/globals.css`, projected into Tailwind v4
through `@theme inline`. Light mode is the reference; dark mode is a
**separate selection**, not a computed flip.

### Surfaces and ink

```
--background  #eef0f4   page — deliberately darker than the cards
--card        #ffffff   every card reads as a raised sheet
--foreground  #0b0d12   primary ink
--muted-foreground #5b6272   secondary ink
--subtle      #8b92a3   tertiary ink — small labels, axes, captions
--border      #e8eaf0   hairline
--line-2      #f0f2f6   the fainter rule — gridlines, row splits
```

Three ink steps, not two: headings, body, and the label under a figure each
need their own weight. Most borders are hairlines, so the **page/card
lightness difference is what carries the layout** — do not darken the cards
or lighten the page.

Cards use `--card-shadow` (hairline + wide low-opacity lift), never
Tailwind's `shadow-sm`. The floating sidebar uses `--glass`,
`--glass-border`, `--glass-shadow` so the component never branches on theme.

### Brand and status

```
--lime  oklch(0.85 0.2 110)   brand; UI accents only
--good  #12A150
--bad   #E5484D
--warn  #B25E09
```

Status colours are **reserved** — never reused as a series colour, never
used alone (always with an icon or a word).

### Data colours

```
--chart-1 #8a8a00   the brand lime, stepped down for a light surface
--chart-2 #4a3aa7
--chart-3 #eb6834
```

The brand lime itself is far too light to sit on white as a data mark, which
is why `chart-1` is a stepped version rather than `--lime`. **These are
validated** for CVD separation, the normal-vision separation floor, and
contrast against the card surface. Do not hand-tune them without re-running
the validator in the `dataviz` skill (`scripts/validate_palette.js`).

### Dataviz rules in force

Applied throughout `frontend/src/components/admin/charts.tsx`:

- One hue for a narrowing measure (the funnel is one hue at three opacities).
- A legend whenever there are ≥ 2 series; identity is never colour-alone.
- A prior period is a **dashed line in the same hue**, never a second hue.
- Axis text is **HTML, never SVG `<text>`** under
  `preserveAspectRatio="none"` — it stretches.
- Never a dual-axis chart.
- A flat series renders as a flat mid-height line; an all-zero series
  renders as a dashed rule, so "no data" and "zero" do not look the same.
- A gauge with no reading says "not reported" rather than showing 0.

---

## 4. The kit

`frontend/src/components/kit/` is the shared vocabulary. Three files:

**`index.tsx`** — layout and display:
`Card` · `CardHead` · `CardBody` · `PageHead` · `PageTitle` · `PageActions` ·
`BackLink` · `TwoCol` · `Tabs` · `SelectChip` · `Chip` · `ChipCount` · `Tag` ·
`PrimaryButton` · `RailLink` · `DotsMenu` · `Avatar` · `PlatformIcon` ·
`FigureLine` · `FigureStrong` · `StackBar` · `Legend` · `Minis` · `Progress` ·
`KV` · `Empty` · `Note` · `Skeleton` · `useCollapsed` · `CollapseButton` ·
plus the table class constants `TH` / `TD` / `MONO` and the tone maps
`CAMPAIGN_TONE` / `TARGET_TONE`.

**`dialog.tsx`** — everything modal and form:
`Dialog` · `DialogHead` · `DialogBody` · `DialogFoot` · `ConfirmDialog` ·
`Field` · `FieldLabel` · `Hint` · `Input` · `Textarea` · `Checkbox` · `Radio` ·
`Steps` · `GhostButton` · `DangerButton`.

**`format.ts`** — `relativeTime`, `apiErrorMessage`.

Two API notes that have already cost time:

- **`Field` has no `hint` prop.** Use `FieldLabel` plus a local explanation
  element. Do not wrap a button-based control in a `<label>`.
- **`ConfirmDialog` takes `body` / `bullets` / `keeps` / `note` /
  `confirmLabel` / `confirmText` / `busy`** — not `danger`, and not children.
  `confirmText` is the string the user must type to arm the button.

### The equal-height rule (new, and the most recently learned)

Cards that share a row must end level. The mechanism:

```tsx
<TwoCol                                  // grid, items-stretch
  main={<Card className="flex flex-1 flex-col">
          <CardHead …/>
          <CardBody className="flex flex-1 flex-col">
            …
            <Minis className="mt-auto" … />   // the floor
          </CardBody>
        </Card>}
  rail={…}
/>
```

`TwoCol` was `items-start`, which made equal height *impossible* — each
column was only as tall as its own contents, so nothing had a height to grow
into. It is `items-stretch` now. A card opts in by asking to fill
(`flex flex-1 flex-col` on the card *and* its body); a card that does not ask
keeps its natural height, which is what a rail holding a stack of three
wants. The last element in a filling card takes `mt-auto` so the slack reads
as a floored card rather than a hole. `RailLink` and `Minis` both accept
`className` for exactly this.

**Do not force equal height on a stack-vs-card row.** See §6.

---

## 5. The shell

`frontend/src/components/AppShell.tsx` is the switchboard. Three lists drive
everything:

- **`PUBLIC_PATHS`** — `/login`, `/register`, `/`, `/terms`, `/privacy`.
  Rendered bare, no shell.
- **`REDESIGNED`** — `/outreach`, `/music`, `/schedule`, `/posts`, `/brands`,
  `/settings`, `/help`, `/admin` (prefix match, so `/posts/new` is included).
  These drop `TopBar` entirely. **When the last page converts, `TopBar` is
  deleted** and the sidebar carries the session controls everywhere.
- **`NO_ASSISTANT`** — `/dashboard`, `/account`, `/oauth`, `/admin`.

### The two rails

`Sidebar.tsx` is the user rail: Create (Dashboard, New Post, Clipping, Audio
to Video, Outreach) · Library (Posts, Brands, Music, Schedule) · Workspace
(Settings, Help & Support).

Below the menu, separated by a rule, admins get **Switch to admin** —
deliberately *not* a nav row, because admin is a different place with its own
rail, and a row in the list would promise that pressing it keeps you here.

`components/admin/AdminSidebar.tsx` is the admin rail, same glass panel,
shield mark on lime, "Admin area" tag in `--warn`. **Back to user dash sits
above the nav**, not at the bottom: leaving is not the last item on a list of
admin pages, it is the thing you want when you opened this by accident. Nav
groups: Overview · People (Users, Approvals) · Content · Reach · System.
Rows not yet redesigned point at `/admin/tools?tab=…`, so the tabbed page is
reached at the right tab rather than at the top of a tab strip. Live badges
on Users and Approvals; **no badge on Error log**, because
`/api/admin/error-logs` returns the newest 200 and no total, and a number
there would be the page size wearing the costume of a count.

---

## 6. Page inventory

| Route | State | Notes |
|---|---|---|
| `/posts` `/posts/new` `/brands` `/music` `/schedule` `/settings` `/help` | **Done** | kit, bare shell |
| `/outreach` `/outreach/[id]` `/outreach/accounts` `/outreach/templates` | **Done** | kit, bare shell |
| `/dashboard` | **Redesigned, not converted** | Bespoke components, imports nothing from the kit, and is **not** in `REDESIGNED` — so it still carries `TopBar`. Reconciling this is open work |
| `/account` | **Untouched** | old design, TopBar |
| `/clipping` `/clipping/[slug]` `/clipping/audio-to-video` | **Untouched** | old design; also the source of the pre-existing lint errors |
| `/admin` `/admin/users` `/admin/users/[id]` `/admin/approvals` `/admin/assistant` | **Done** | new admin rail |
| `/admin/tools` | **Moved, not redesigned** | the old 13-tab page; Overview and Users tabs removed, heading now "Everything else" |
| `/login` `/register` | **Done** | `(auth)` route group sharing one layout (`components/auth/`), so the photo stage persists across the tab switch. Email + password only — the backend has no Apple/Google sign-in, so no buttons for them. The stage's cards are illustrations and `aria-hidden`; only the week strip is real dates |
| `/` `/terms` `/privacy` `/oauth/callback` | **Out of scope so far** | |

### Alignment: the three rows left ragged on purpose

The sweep still flags these, and it should:

- **`/help`** — a rail *stack* beside one tall card. The columns already end
  dead level (gap 0); there is no pair to align.
- **`/outreach/[id]`** — a 1,454px target table beside five small cards.
  Stretching the last rail card to ~1,150px would be far worse than the gap.
- **`/dashboard`** — two cards left, three right. No pair; columns finish
  14px apart.

### The one cost of the alignment

**Settings → "Set somewhere else"** now carries roughly 170px of blank tail,
because it holds two rows next to a card holding five. This was a conscious
trade (spreading the rows out looked worse) and the same call was already
made on `/help`. It is the first thing to revisit if the user dislikes it.

---

## 7. Constraints that bite

Lint rules that are **errors** in this repo, each of which has already broken
a build during this work:

- **`react-hooks/purity`** — no `Date.now()` during render. Move it to a
  module-level function (see `signedInThisWeek()` in
  `app/admin/approvals/page.tsx`).
- **`react-hooks/set-state-in-effect`** — no synchronous `setState` reachable
  from an effect body. The working pattern: split `load()` (never touches
  state before a request is in flight) from `refresh()` (`setBusy(true);
  load()`), and have the effect call `load()`. A "quiet" flag does **not**
  satisfy the rule.
- **`@typescript-eslint/no-explicit-any`**.
- **`useSearchParams()` must sit behind `<Suspense>`** or the route cannot be
  prerendered. `/admin/tools` wraps its own body for this reason.

Non-lint, learned the hard way:

- Postgres foreign keys with no `ON DELETE` rule default to NO ACTION and
  **block the parent delete**. This is what made a user with a campaign
  undeletable.
- Scripted edits that "succeed" silently: a `.replace()` that does not match
  replaces text with itself and reports success. A blanket `s.replace(line,
  '')` once removed three identical `useState` declarations and broke two
  unrelated cards. **Assert the match count**, and re-lint after any scripted
  edit.

---

## 8. The verification harness — read this before running anything

### The safety problem

The local backend at `localhost:8000` is configured with
`postgresql+asyncpg://…@127.0.0.1:5432/icreateflow` — **that is production.**
Any write the browser makes while you are "just looking at a page" lands on
real rows.

So every Playwright run **registers a catch-all route before the first
navigation** that fulfils any non-GET request to `/api/` with a 403 and
records it, and every run prints `writes blocked: …` at the end. During the
admin work the Save button on the user detail page was fired twice on
purpose: two `PUT /api/admin/users/1` were intercepted and the production row
still read `Admin / True` afterwards. Do that kind of check rather than
trusting the guard silently.

### Rebuilding the harness

The scratchpad is **wiped between sessions** — assume it is empty. Four
files reconstruct it:

- **`mint.py`** — loads `/Users/mac/icreateflow-local/backend/.env` into the
  environment, imports `database` and `services.auth.create_access_token`,
  selects the lowest-id admin, and writes `{token, id, email, name, role}` as
  `token.json`. Read-only by intent; it exists only so you do not need a
  password to look at a page.
- **`live.py`** — the three helpers every script imports:
  `guard(context)` (the write blocker, returns the list it fills),
  `page_with_token(context)` (init script setting `localStorage.icreate_token`
  and `theme`), and `shoot(page, url, out, …)` (viewport, `networkidle`,
  settle, screenshot, and returns page errors + horizontal overflow + height).
- **`align.py`** — the alignment sweep. Collects every opaque `rounded-[18px]`
  element inside `<main>`, groups them into rows by top edge within 4px, and
  reports any row whose heights differ by more than 8px. Runs the full 22-route
  list.
- **`leak_sweep.py`** — the admin-leak sweep. For each of the ten user routes,
  counts `main a[href^="/admin"]`, records any `/api/admin/` request, and
  searches the main text for `oauth_redirect_base`, `public address is unset`
  and `on admin`. **Looks inside `<main>` only**, because the sidebar's switch
  is chrome, role-gated, and the whole point of it is to leave. Ends with
  `still leaking: nothing` when clean.

Both sweeps are cheap and both have caught real regressions. Run them after
any page change.

### Other gotchas

- Full-page screenshots truncate `position: fixed` sidebars. Confirm rail
  geometry with `bounding_box()` and a link count, not the image.
- `DotsMenu` renders `role="button"` + `aria-label` on the trigger and plain
  `<button>` / `<Link>` items — **not** `role="menuitem"`. Locate with
  `[role=button][aria-label^='Actions']` then `[role=menu] button`.
- Restarting uvicorn: check first that no outreach campaign is `running`.

---

## 9. Backend work the previews specify but nobody has written

The admin previews were designed against what the product should do, and the
gaps were tagged rather than hidden. Each of these is a real piece of backend
work someone has to decide on:

- Admin password reset endpoint(s) and token invalidation.
- Admin-scoped repair endpoints — the existing ones are `_own_account` /
  `_scope` gated, so an admin cannot run them for someone else.
- Profile columns (phone, location, company, timezone) — or `user_settings`
  rows — plus a `PUT` that accepts them.
- Subscriptions/payments tables, a provider webhook, and an AI usage log.
  Until these exist the whole "Plan & payment" card is `sample`.
- Assistant thread/message tables and a model behind the Ask panel.
- An approval email, and a "refused" state. Right now **Refuse deletes the
  account**, and the dialog says so plainly because there is nowhere else for
  a refused signup to go.
- A total count on the error log (see §5).
- There is no `GET /api/admin/users/{id}`; the user detail page reads one
  person out of `getUsers()`, which is why `get_users()` now selects
  `email_notifications` (and still never the password hash or unsubscribe
  token).

### Backend changes already made in this working tree

- `admin_delete_user` cascade extended to `artists` and all six outreach
  tables, so **anyone can be deleted**, including someone mid-campaign. One
  commit, so either the whole account goes or none of it does.
- `AdminUserUpdate` gained `email` (with a uniqueness check returning a
  sentence) and `email_notifications`, kept with `is not None` rather than a
  truth test so turning a switch off is not silently dropped.
- Three new test files: `test_admin_delete_user.py`,
  `test_admin_update_user.py`, `test_outreach_summary.py`. The first two
  carry an autouse `_clean` fixture that deletes only their own addresses —
  the users table is not truncated between runs, so a rename test collides
  with itself on the second run without it.

---

## 10. Open questions the user has not answered

Carry these forward; do not decide them unilaterally.

1. **The Apollo typeface.** The light theme is described in `globals.css` as
   "Apollo-inspired" but no licensed face has been chosen. Asked, unanswered.
2. **`CardHead` at 14.5px → 16px** — applied, but never confirmed as a
   system-wide change.
3. **`LINGER = 12000`** — is 12s the right retire time for the assistant
   nudge? And the nudge note overlaps the pager arrows bottom-right.
4. **Is the admin nav list the right set of pages?** Should be settled before
   more admin pages are built, since every new one changes the rail.
5. **The Settings blank tail** (§6).
6. **`/dashboard`**: convert it to the kit and add it to `REDESIGNED`, or
   leave it bespoke with a TopBar? It is currently the only inconsistency a
   user can see.

---

## 11. Suggested order when work resumes

Nothing here is decided — the user picks.

1. Settle §10.4 (the admin nav list), because it is cheap now and expensive
   later.
2. `/dashboard` — the visible inconsistency, and the last blocker on deleting
   `TopBar`.
3. `/account`, then the three `/clipping` pages. Finishing these deletes
   `TopBar` and clears the remaining lint errors in one pass.
4. `/admin/tools` — break the remaining 11 tabs out into real admin pages,
   retiring the tabbed page tab by tab.
5. Only then: the backend gaps in §9, so the `sample` tags and `no endpoint`
   pills can come off one at a time.
