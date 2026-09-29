package com.icreateflow.companion.engine

import android.content.Context
import kotlinx.coroutines.delay

/**
 * One unfollow, start to finish — a port of `android_tiktok.py`'s
 * `_unfollow`, proven over the cable on 2026-09-24 (@depay038,
 * followers 2,268 → 2,267).
 *
 * It can never follow anyone: only a control reading Following, Friends or
 * Requested is pressed. A profile showing Follow is "not following" — a
 * success with nothing pressed.
 *
 * Tapping Following opens a bottom sheet whose lowest entry is Unfollow (or
 * "Cancel request" for a pending one). A mutual follow ("Friends") is asked
 * once more — "Unfollow this person? You and this person are currently
 * friends." — Cancel | Unfollow. Then the profile is reopened, and only that
 * reading counts.
 */
object Unfollower {
    const val NOT_FOLLOWING = "not_following"

    private const val SHEET_WAIT_MS = 8_000L
    private const val POLL_MS = 700L
    private val CHOICES = setOf("unfollow", "cancel request")

    suspend fun unfollow(
        ctx: Context, me: String, who: String,
        say: (String, Boolean?) -> Unit = { _, _ -> },
    ): Follower.Outcome {
        fun fail(status: String, error: String, line: String = error): Follower.Outcome {
            say(line, false); return Follower.Outcome(status, error)
        }
        val svc = FollowService.instance
            ?: return fail(Follower.DEVICE_UNAVAILABLE, "The phone service is switched off")
        Follower.prepare(ctx, svc, me, say)?.let { return it }

        say("Opening @$who…", null)
        val view = Follower.open(svc, who)
        when {
            view.challenge -> return fail(Follower.CHALLENGE_REQUIRED,
                "TikTok on the phone is showing a verification puzzle — solve it on the phone, then resume the campaign")
            view.loginWall -> { Follower.forgetIdentity(); return fail(Follower.DEVICE_UNAVAILABLE,
                "TikTok on the phone is signed out — sign in to @$me") }
            view.missing -> return fail(Follower.PROFILE_UNAVAILABLE, "Profile not found", "@$who doesn't exist")
            !sameHandle(view.handle, who) && view.feed -> {
                say("TikTok opened its For You feed instead of the profile", false)
                return Follower.feedInstead(who)
            }
            !sameHandle(view.handle, who) -> return if (svc.snapshot().isEmpty())
                fail(Follower.DEVICE_UNAVAILABLE, "TikTok did not come to the front — the phone will try again shortly")
            else fail(Follower.NAVIGATION_TIMEOUT, "@$who's profile did not load on the phone")
            view.isSelf -> return fail(Follower.MESSAGING_UNAVAILABLE, "That is this account's own profile")
            view.state == "can_follow" -> {
                say("@$who isn't followed — nothing pressed", true)
                return Follower.Outcome(NOT_FOLLOWING)
            }
            view.state !in setOf("following", "pending") || view.control == null ->
                return fail(Follower.MESSAGING_UNAVAILABLE, "No follow control on @$who's profile")
        }

        say("Tapping ${view.control!!.text.trim()} on @$who…", null)
        if (!svc.tap(view.control.cx, view.control.cy))
            return fail(Follower.DEVICE_UNAVAILABLE, "Android did not deliver the tap")

        var choice: Node? = null
        val sheetBy = System.currentTimeMillis() + SHEET_WAIT_MS
        while (System.currentTimeMillis() < sheetBy) {
            delay(POLL_MS)
            // The sheet rises from the bottom; its entry is the lowest one.
            choice = svc.snapshot().filter { it.label in CHOICES }.maxByOrNull { it.top }
            if (choice != null) break
        }
        if (choice == null) {
            svc.back()
            return fail(Messenger.UNEXPECTED_PAGE, "Tapping Following on @$who opened no Unfollow option")
        }
        say("Choosing ${choice.text.trim()}…", null)
        if (!svc.tap(choice.cx, choice.cy)) return fail(Follower.DEVICE_UNAVAILABLE, "Android did not deliver the tap")

        // A mutual follow is asked once more: Cancel | Unfollow.
        var after = ProfileView()
        var confirmed = false
        var by = System.currentTimeMillis() + SHEET_WAIT_MS
        while (System.currentTimeMillis() < by) {
            delay(POLL_MS)
            val nodes = svc.snapshot()
            after = readProfile(nodes)
            if (after.challenge || after.state == "can_follow") break
            if (!confirmed) {
                val again = nodes.firstOrNull { it.label == "unfollow" }
                if (again != null && nodes.any { it.label == "cancel" }) {
                    say("TikTok asks again (you're friends) — confirming Unfollow", null)
                    svc.tap(again.cx, again.cy)
                    confirmed = true
                    by = System.currentTimeMillis() + SHEET_WAIT_MS
                }
            }
        }
        if (after.challenge) return fail(Follower.CHALLENGE_REQUIRED, "TikTok showed a verification puzzle after the tap")

        say("Reopening @$who to check it stuck…", null)
        val again = Follower.open(svc, who)
        return when {
            sameHandle(again.handle, who) && again.state == "can_follow" -> {
                say("Unfollowed — the profile says Follow after reopening", true)
                Follower.Outcome(Follower.SENT, null, mapOf("action" to "unfollow",
                    "followers_before" to (view.followers ?: ""), "followers_after" to (again.followers ?: "")))
            }
            after.state == "can_follow" -> fail(Follower.FOLLOW_DISCARDED,
                "@$who showed Follow after unfollowing, but Following again after reopening — TikTok did not keep the unfollow")
            else -> {
                val said = after.limitNotice
                say("Still followed after tapping Unfollow", false)
                Follower.Outcome(Follower.FOLLOW_LIMITED,
                    said ?: "@$who is still followed after Unfollow was tapped — the account has most likely hit its limit",
                    listOfNotNull(said?.let { "platform_said" to it }).toMap())
            }
        }
    }
}
