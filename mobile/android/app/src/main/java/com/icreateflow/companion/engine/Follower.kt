package com.icreateflow.companion.engine

import android.app.KeyguardManager
import android.content.Context
import android.util.Log
import kotlinx.coroutines.delay

/**
 * One follow, start to finish, answered in the server's own words.
 *
 * The sequence of `android_tiktok.py`'s `_follow`, which the cabled phone
 * proved: check who TikTok is signed in as, open the target, tap its own
 * Follow, watch the button, reopen and read again. Every exit is a status
 * from `services/outreach/constants.py`, so the server routes it exactly as
 * it routes the cabled phone's — a limit stands the campaign down, a phone
 * hiccup brings the person back a minute later. Nothing pauses the account.
 *
 * Used by the test on the Phone tab and by campaign follows alike: the
 * test is this, with nothing reported to the server.
 */
object Follower {
    data class Outcome(val status: String, val error: String? = null, val detail: Map<String, String> = emptyMap()) {
        val success get() = status in setOf(SENT, ALREADY_FOLLOWING, FOLLOW_REQUESTED, "not_following")
    }

    const val SENT = "sent"
    const val ALREADY_FOLLOWING = "already_following"
    const val FOLLOW_REQUESTED = "follow_requested"
    const val FOLLOW_DISCARDED = "follow_discarded"
    const val FOLLOW_LIMITED = "follow_limited"
    const val DEVICE_UNAVAILABLE = "device_unavailable"
    const val CHALLENGE_REQUIRED = "challenge_required"
    const val PROFILE_UNAVAILABLE = "profile_unavailable"
    const val NAVIGATION_TIMEOUT = "navigation_timeout"
    const val MESSAGING_UNAVAILABLE = "messaging_unavailable"
    const val RATE_LIMITED = "rate_limited"

    /**
     * The answer when neither the link nor TikTok's search brings a profile
     * up and the feed shows instead: TikTok isn't letting this account open
     * profiles, so the campaign waits it out and nobody is charged. Only
     * after search too — a link alone lands on the feed for particular
     * profiles that search opens fine (see `open`).
     */
    internal fun feedInstead(who: String) = Outcome(RATE_LIMITED,
        "TikTok opened its For You feed instead of @$who's profile, and its search didn't open " +
            "either — it isn't opening profiles for this account for now",
        mapOf("platform_said" to "TikTok is opening its For You feed instead of profiles"))

    private const val PROFILE_WAIT_MS = 20_000L
    private const val CONFIRM_WAIT_MS = 8_000L
    private const val POLL_MS = 1_000L
    private const val RETRY_OPEN_MS = 1_000L
    private const val SEARCH_WAIT_MS = 12_000L
    private const val RESULTS_SETTLE_MS = 4_000L
    private const val SEARCH_TAPS = 2
    private const val SEARCH_OPEN_MS = 10_000L
    private const val STEADY_MS = 600L
    private const val FEED_SETTLE_MS = 4_000L
    /** How long a confirmed identity is trusted before it is checked again. */
    private const val IDENTITY_TTL_MS = 10 * 60_000L

    private var confirmed: Pair<String, Long>? = null

    /** Forget who TikTok was signed in as — the next follow checks again. */
    fun forgetIdentity() { confirmed = null }

    /**
     * Open a profile: by link, and if that doesn't bring it up, through
     * TikTok's own search, as a person would.
     *
     * A link makes TikTok look the name up, and for some profiles that
     * lookup fails and TikTok shows the For You feed instead — the same
     * profiles every time, while the ones either side open in two seconds
     * (2026-09-28: @kayceebob1 three times in two days, 453 followers,
     * perfectly real). Searching the name opened it at once. Opening by
     * link twice used to be the retry; the second try failed the same way.
     *
     * Search also settles what a link can't: no result named exactly
     * `handle` means the profile is gone or renamed — that person is
     * skipped, and the campaign carries on.
     */
    internal suspend fun open(svc: FollowService, handle: String): ProfileView {
        val byLink = openOnce(svc, handle)
        if (loaded(byLink, handle)) return byLink
        Log.i(FollowService.TAG, "link didn't open @$handle (${if (byLink.feed) "For You feed" else "no profile"}) — searching")
        delay(RETRY_OPEN_MS)
        return bySearch(svc, handle) ?: byLink
    }

    /** The profile through search; null if search itself didn't come up. */
    private suspend fun bySearch(svc: FollowService, handle: String): ProfileView? {
        svc.openSearch(handle)
        var search = waitSearch(svc, handle, SEARCH_WAIT_MS)
            ?: return null.also { Log.i(FollowService.TAG, "search didn't come up for @$handle") }
        if (search.hit == null && search.usersTab != null) {
            // "Top" leads with a profile only when it's a strong match; the
            // Users tab lists every account by name.
            svc.tap(search.usersTab!!.cx, search.usersTab!!.cy)
            delay(POLL_MS)
            search = waitSearch(svc, handle, SEARCH_WAIT_MS, needHit = true) ?: search
        }
        if (search.hit == null) {
            Log.i(FollowService.TAG, "search has no account named @$handle")
            return ProfileView(missing = true)
        }
        // Two tries: results shift as the videos under them load, and a tap
        // on a moving list can land on a video instead (2026-09-28, once in
        // five). A miss goes back to the results and taps the name again.
        var view = ProfileView()
        repeat(SEARCH_TAPS) { attempt ->
            val hit = steadyHit(svc, handle) ?: return view
            Log.i(FollowService.TAG, "search found @$handle at ${hit.cx},${hit.cy} — opening it")
            if (!svc.tap(hit.cx, hit.cy)) return null
            val deadline = System.currentTimeMillis() + SEARCH_OPEN_MS
            while (System.currentTimeMillis() < deadline) {
                delay(POLL_MS)
                view = readProfile(svc.snapshot())
                if (loaded(view, handle)) return view
            }
            Log.i(FollowService.TAG, "after search tap ${attempt + 1}: handle=${view.handle} state=${view.state}")
            if (!readSearch(svc.snapshot(), handle).showing) {
                svc.back()
                delay(RETRY_OPEN_MS)
            }
        }
        return view
    }

    /** The result line, once it's in the same place on two reads running. */
    private suspend fun steadyHit(svc: FollowService, handle: String): Node? {
        var last: Node? = null
        val start = System.currentTimeMillis()
        while (System.currentTimeMillis() - start < SEARCH_WAIT_MS) {
            val hit = readSearch(svc.snapshot(), handle).hit
            if (hit != null && last != null && kotlin.math.abs(hit.cy - last.cy) < 8) return hit
            last = hit
            delay(STEADY_MS)
        }
        return last
    }

    private suspend fun waitSearch(
        svc: FollowService, handle: String, waitMs: Long, needHit: Boolean = false,
    ): SearchView? {
        val start = System.currentTimeMillis()
        var last: SearchView? = null
        while (System.currentTimeMillis() - start < waitMs) {
            delay(POLL_MS)
            val s = readSearch(svc.snapshot(), handle)
            if (s.showing) {
                last = s
                if (s.hit != null) return s
                // Results arrive a moment after the tabs; give them a few polls.
                if (!needHit && System.currentTimeMillis() - start > RESULTS_SETTLE_MS) return s
            }
        }
        return last
    }

    private fun loaded(v: ProfileView, handle: String) =
        v.challenge || v.missing || v.loginWall || (sameHandle(v.handle, handle) && (v.state != null || v.isSelf))

    private suspend fun openOnce(svc: FollowService, handle: String): ProfileView {
        svc.openProfile(handle)
        val deadline = System.currentTimeMillis() + PROFILE_WAIT_MS
        var view = ProfileView()
        var feedSince = 0L
        while (System.currentTimeMillis() < deadline) {
            delay(POLL_MS)
            view = readProfile(svc.snapshot())
            if (view.challenge || view.missing || view.loginWall) return view
            if (sameHandle(view.handle, handle) && (view.state != null || view.isSelf)) return view
            // Settled on the feed: the link isn't going to open it — don't
            // sit out the full wait (it cost 40s a person).
            if (view.feed) {
                if (feedSince == 0L) feedSince = System.currentTimeMillis()
                else if (System.currentTimeMillis() - feedSince >= FEED_SETTLE_MS) return view
            } else feedSince = 0L
        }
        return view
    }

    /**
     * @param say one line per step, for the Phone tab's log.
     * @param recheckMs how long to wait before the reopen that confirms it.
     */
    suspend fun follow(
        ctx: Context, me: String, who: String, recheckMs: Long,
        say: (String, Boolean?) -> Unit = { _, _ -> },
    ): Outcome {
        fun fail(status: String, error: String, line: String = error): Outcome {
            say(line, false); return Outcome(status, error)
        }

        val svc = FollowService.instance
            ?: return fail(DEVICE_UNAVAILABLE, "The follow service on the phone is switched off")
        prepare(ctx, svc, me, say)?.let { return it }
        return followOn(svc, me, who, recheckMs, say)
    }

    /**
     * What every job checks first: the phone can work, and TikTok is signed
     * in as `me`. Null when it's good to go; otherwise the answer to report.
     */
    internal suspend fun prepare(
        ctx: Context, svc: FollowService, me: String, say: (String, Boolean?) -> Unit,
    ): Outcome? {
        fun fail(status: String, error: String, line: String = error): Outcome {
            say(line, false); return Outcome(status, error)
        }
        if (FollowService.installedTikTok(ctx) == null)
            return fail(DEVICE_UNAVAILABLE, "TikTok isn't installed on the phone")
        val keyguard = ctx.getSystemService(KeyguardManager::class.java)
        if (keyguard?.isKeyguardLocked == true)
            return fail(DEVICE_UNAVAILABLE, "The phone is locked — nothing was tapped")

        val known = confirmed
        if (known == null || !sameHandle(known.first, me) || System.currentTimeMillis() - known.second > IDENTITY_TTL_MS) {
            say("Checking TikTok is signed in as @$me…", null)
            val self = open(svc, me)
            if (self.loginWall) return fail(DEVICE_UNAVAILABLE, "TikTok on the phone is signed out — sign in to @$me")
            if (self.challenge) return fail(CHALLENGE_REQUIRED,
                "TikTok on the phone is showing a verification puzzle — solve it on the phone, then resume the campaign")
            // "Wrong account" only when TikTok actually shows it: @me's
            // profile opened as somebody else's (with a Follow button). A
            // profile that simply didn't load says nothing about who is
            // signed in — it was reported as the wrong account once, six
            // seconds after the account was switched back on.
            if (sameHandle(self.handle, me) && !self.isSelf && self.state != null) {
                confirmed = null
                return fail(DEVICE_UNAVAILABLE,
                    "TikTok on the phone is signed in to a different account, not @$me — nothing was tapped",
                    "TikTok is signed in to a different account")
            }
            if (!(sameHandle(self.handle, me) && self.isSelf)) {
                return fail(DEVICE_UNAVAILABLE,
                    "TikTok didn't show @$me's profile in time — the phone will try again shortly",
                    "Couldn't load @$me's profile to check the account")
            }
            confirmed = me to System.currentTimeMillis()
            say("Signed in as @$me", true)
        }
        return null
    }

    private suspend fun followOn(
        svc: FollowService, me: String, who: String, recheckMs: Long, say: (String, Boolean?) -> Unit,
    ): Outcome {
        fun fail(status: String, error: String, line: String = error): Outcome {
            say(line, false); return Outcome(status, error)
        }
        say("Opening @$who…", null)
        val before = open(svc, who)
        when {
            before.challenge -> return fail(CHALLENGE_REQUIRED,
                "TikTok on the phone is showing a verification puzzle — solve it on the phone, then resume the campaign")
            before.loginWall -> { confirmed = null; return fail(DEVICE_UNAVAILABLE, "TikTok on the phone is signed out — sign in to @$me") }
            before.missing -> return fail(PROFILE_UNAVAILABLE, "Profile not found", "@$who doesn't exist")
            !sameHandle(before.handle, who) && before.feed -> {
                say("TikTok opened its For You feed instead of the profile", false)
                return feedInstead(who)
            }
            !sameHandle(before.handle, who) -> return if (svc.snapshot().isEmpty())
                fail(DEVICE_UNAVAILABLE, "TikTok did not come to the front — the phone will try again shortly")
            else fail(NAVIGATION_TIMEOUT, "@$who's profile did not load on the phone")
            before.isSelf -> return fail(MESSAGING_UNAVAILABLE, "That is this account's own profile")
            before.state == "following" -> { say("Already following @$who — nothing tapped", true); return Outcome(ALREADY_FOLLOWING) }
            before.state == "pending" -> { say("A request to @$who is already waiting", true); return Outcome(FOLLOW_REQUESTED) }
            before.state != "can_follow" || before.control == null ->
                return fail(MESSAGING_UNAVAILABLE, "No follow button on @$who's profile")
        }
        say("@$who has ${before.followers ?: "?"} followers — tapping Follow", true)

        val control = before.control!!
        if (!svc.tap(control.cx, control.cy)) return fail(DEVICE_UNAVAILABLE, "Android did not deliver the tap")

        var after = ProfileView()
        val deadline = System.currentTimeMillis() + CONFIRM_WAIT_MS
        while (System.currentTimeMillis() < deadline) {
            delay(POLL_MS)
            after = readProfile(svc.snapshot())
            if (after.challenge || after.state == "following" || after.state == "pending") break
        }
        when {
            after.challenge -> return fail(CHALLENGE_REQUIRED, "TikTok showed a verification puzzle after the tap")
            after.state == "pending" -> { say("Private account — request sent", true); return Outcome(FOLLOW_REQUESTED) }
            after.state != "following" -> {
                val said = after.limitNotice
                return Outcome(FOLLOW_LIMITED,
                    said ?: "The Follow button on @$who did not change after being tapped on the phone — " +
                        "the account has most likely hit its follow limit",
                    listOfNotNull(said?.let { "platform_said" to it }).toMap()).also {
                    say("The button didn't change", false)
                }
            }
        }
        say("Button now says Following", true)

        // Reopening can show TikTok's cached "Following" for a follow it has
        // already dropped, and its cached follower count for one it kept —
        // one app can't restart another to clear either. So: a Follow on
        // reopen is a drop, a risen count is proof, and anything else is
        // taken at the button's word, as the cabled phone does.
        if (recheckMs > 0) {
            say("Waiting ${recheckMs / 1000}s, then reopening @$who…", null)
            delay(recheckMs)
        } else say("Reopening @$who…", null)
        val again = open(svc, who)
        val counts = "followers ${before.followers ?: "?"} → ${again.followers ?: "?"}"
        val detail = mapOf("followers_before" to (before.followers ?: ""), "followers_after" to (again.followers ?: ""))
        return when {
            sameHandle(again.handle, who) && again.state == "can_follow" -> Outcome(FOLLOW_DISCARDED,
                "@$who showed Following after the tap but Follow again after reopening — TikTok did not keep the follow",
                detail).also { say("After reopening it says Follow again", false) }
            sameHandle(again.handle, who) && again.state == "following" -> Outcome(SENT, null, detail).also {
                say("Still Following after reopening · $counts", true)
            }
            else -> Outcome(SENT, null, detail).also { say("Couldn't read the profile after reopening", null) }
        }
    }
}
