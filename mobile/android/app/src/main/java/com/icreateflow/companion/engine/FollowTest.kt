package com.icreateflow.companion.engine

import android.content.Context
import android.content.Intent
import android.util.Log
import com.icreateflow.companion.MainActivity
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

/**
 * The Phone tab's "Test one follow": one follow by `Follower`, shown step by
 * step, reported to nobody.
 *
 * Proven 2026-09-26: the app's own tap followed @officialhelend26 and after
 * a TikTok restart it read Following, 1,049 → 1,050.
 */
object FollowTest {
    enum class Outcome { Followed, AlreadyFollowing, Requested, Discarded, Unchanged, Failed }

    data class Step(val text: String, val ok: Boolean? = null)
    data class Run(
        val running: Boolean = false,
        val steps: List<Step> = emptyList(),
        val outcome: Outcome? = null,
        val summary: String? = null,
    )

    /**
     * A target handed in from outside the screen — review builds only
     * (`adb shell am start … --es follow_target someone`), so a test can be
     * set up from the Mac without typing into the phone.
     */
    val prefill = MutableStateFlow<String?>(null)

    private val _state = MutableStateFlow(Run())
    val state: StateFlow<Run> = _state
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    /** The test waits longer than a job before its reopen: someone is watching it. */
    private const val RECHECK_MS = 30_000L

    private fun say(text: String, ok: Boolean?) {
        Log.i(FollowService.TAG, "step ${when (ok) { true -> "ok"; false -> "FAIL"; null -> ".." }} $text")
        _state.value = _state.value.copy(steps = _state.value.steps + Step(text, ok))
    }

    fun start(ctx: Context, myHandle: String, target: String) {
        if (_state.value.running || FollowJobs.state.value.on) return
        val me = myHandle.trim().removePrefix("@")
        val who = target.trim().removePrefix("@")
        _state.value = Run(running = true)
        val app = ctx.applicationContext
        scope.launch {
            Follower.forgetIdentity()
            val out = Follower.follow(app, me, who, RECHECK_MS, ::say)
            val (outcome, summary) = describe(out, who)
            Log.i(FollowService.TAG, "result ${out.status} ${out.error ?: ""}")
            _state.value = _state.value.copy(running = false, outcome = outcome, summary = summary)
            // Come back to the app so the result is on screen.
            app.startActivity(Intent(app, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_REORDER_TO_FRONT))
        }
    }

    /** One unfollow, with the campaign steps, reported to nobody. */
    fun startUnfollow(ctx: Context, myHandle: String, target: String) {
        if (_state.value.running || FollowJobs.state.value.on) return
        val me = myHandle.trim().removePrefix("@")
        val who = target.trim().removePrefix("@")
        _state.value = Run(running = true)
        val app = ctx.applicationContext
        scope.launch {
            Follower.forgetIdentity()
            val out = Unfollower.unfollow(app, me, who, ::say)
            val (outcome, summary) = when (out.status) {
                Follower.SENT -> Outcome.Followed to "Unfollowed @$who, and it stuck after reopening."
                Unfollower.NOT_FOLLOWING -> Outcome.AlreadyFollowing to "You don't follow @$who, so nothing was pressed."
                else -> Outcome.Failed to (out.error ?: "Something went wrong.")
            }
            Log.i(FollowService.TAG, "result ${out.status} ${out.error ?: ""}")
            _state.value = _state.value.copy(running = false, outcome = outcome, summary = summary)
            app.startActivity(Intent(app, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_REORDER_TO_FRONT))
        }
    }

    /** One message to one profile, with the campaign steps, reported to nobody. */
    fun startMessage(ctx: Context, myHandle: String, target: String, text: String) {
        if (_state.value.running || FollowJobs.state.value.on) return
        val me = myHandle.trim().removePrefix("@")
        val who = target.trim().removePrefix("@")
        _state.value = Run(running = true)
        val app = ctx.applicationContext
        scope.launch {
            Follower.forgetIdentity()
            val out = Messenger.send(app, me, who, text, ::say)
            val (outcome, summary) = when (out.status) {
                Follower.SENT -> Outcome.Followed to
                    "Sent: the message is in your chat with @$who. Check it arrived on their side."
                Follower.MESSAGING_UNAVAILABLE -> Outcome.Failed to (out.error ?: "@$who doesn't take messages from this account.")
                Messenger.MESSAGE_REFUSED -> Outcome.Failed to
                    "TikTok refused this message — change the wording. ${out.detail["platform_said"] ?: ""}".trim()
                Messenger.RATE_LIMITED -> Outcome.Unchanged to "TikTok says to slow down. Try again later."
                else -> Outcome.Failed to (out.error ?: "Something went wrong.")
            }
            Log.i(FollowService.TAG, "result ${out.status} ${out.error ?: ""}")
            _state.value = _state.value.copy(running = false, outcome = outcome, summary = summary)
            app.startActivity(Intent(app, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_REORDER_TO_FRONT))
        }
    }

    private fun describe(out: Follower.Outcome, who: String): Pair<Outcome, String> = when (out.status) {
        Follower.SENT -> Outcome.Followed to
            "TikTok still shows Following for @$who. Its follower count updates late, so open the profile " +
            "later to be certain — a follow the limit drops turns back to Follow."
        Follower.ALREADY_FOLLOWING -> Outcome.AlreadyFollowing to
            "You already follow @$who, so nothing was pressed. Pick someone you don't follow."
        Follower.FOLLOW_REQUESTED -> Outcome.Requested to "@$who is private; the request is waiting for them."
        Follower.FOLLOW_DISCARDED -> Outcome.Discarded to
            "TikTok showed Following, then dropped it. That is TikTok's follow limit: this account can't follow " +
            "anyone right now. Try again once the limit resets, usually within a day."
        Follower.FOLLOW_LIMITED -> Outcome.Unchanged to (out.error ?: "The Follow button didn't change.")
        else -> Outcome.Failed to (out.error ?: "Something went wrong.")
    }
}
