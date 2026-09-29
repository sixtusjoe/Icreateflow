package com.icreateflow.companion.engine

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.util.Log
import com.icreateflow.companion.CompanionApp
import com.icreateflow.companion.MainActivity
import com.icreateflow.companion.R
import com.icreateflow.companion.data.Api
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * Taking campaign jobs: while it's on, the phone asks ICREATEFLOW for the
 * next follow or message every few seconds, does it with `Follower` or
 * `Messenger`, and reports what happened (`services/outreach/companion.py`
 * on the server).
 *
 * Nothing about pacing or limits lives here. The server hands out a job
 * only when the campaign's pacing allows one, and decides what a result
 * means — a limit stands the campaign down, a phone hiccup brings the
 * person back a minute later. Nothing pauses the account. One job at a
 * time, honestly reported.
 */
object FollowJobs {
    data class State(
        val on: Boolean = false,
        /** What the phone is doing, in a line — also the notification's text. */
        val line: String = "Off",
        val done: Int = 0,
        val last: String? = null,
    )

    val state: StateFlow<State> get() = _state
    internal val _state = MutableStateFlow(State())

    fun start(ctx: Context) {
        val intent = Intent(ctx, FollowJobsService::class.java)
        if (Build.VERSION.SDK_INT >= 26) ctx.startForegroundService(intent) else ctx.startService(intent)
    }

    fun stop(ctx: Context) {
        ctx.stopService(Intent(ctx, FollowJobsService::class.java))
    }
}

class FollowJobsService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var loop: Job? = null
    private var wake: PowerManager.WakeLock? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        channel()
        val note = notification("Starting…")
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(NOTE_ID, note, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        } else startForeground(NOTE_ID, note)
        if (wake == null) {
            // Taps need a screen that's on. A screen kept on also never
            // locks itself — a phone that was already locked is refused by
            // Follower before anything is touched.
            @Suppress("DEPRECATION")
            wake = getSystemService(PowerManager::class.java)
                .newWakeLock(PowerManager.SCREEN_DIM_WAKE_LOCK or PowerManager.ACQUIRE_CAUSES_WAKEUP, "icf:follows")
                .apply { acquire() }
        }
        if (loop?.isActive != true) loop = scope.launch { run() }
        return START_STICKY
    }

    override fun onDestroy() {
        scope.cancel()
        wake?.let { if (it.isHeld) it.release() }
        wake = null
        FollowJobs._state.value = FollowJobs._state.value.copy(on = false, line = "Off")
        super.onDestroy()
    }

    private fun show(line: String) {
        Log.i(FollowService.TAG, "jobs: $line")
        FollowJobs._state.value = FollowJobs._state.value.copy(on = true, line = line)
        getSystemService(NotificationManager::class.java).notify(NOTE_ID, notification(line))
    }

    private suspend fun run() {
        val session = (application as CompanionApp).session
        val device = session.deviceId
        FollowJobs._state.value = FollowJobs._state.value.copy(on = true)
        while (scope.isActive) {
            val token = session.token
            if (token == null) { show("Signed out — sign in to take follows"); stopSelf(); return }
            val task = try {
                Api.nextTask(token, device)
            } catch (e: Api.ApiError) {
                if (e.status == 401) { show("Signed out — sign in to take follows"); stopSelf(); return }
                show("Can't reach ICREATEFLOW — trying again")
                delay(RETRY_MS); continue
            }
            if (task == null) {
                show(if (FollowService.instance == null) "Waiting — the follow service is off"
                     else "Waiting for follows")
                delay(POLL_MS); continue
            }

            val log: (String, Boolean?) -> Unit = { line, _ -> Log.i(FollowService.TAG, "job ${task.id}: $line") }
            val out = when (task.action) {
                "message" -> {
                    show("Messaging @${task.username}…")
                    Messenger.send(this, task.handle, task.username, task.message.orEmpty(), log)
                }
                "follow" -> {
                    show("Following @${task.username}…")
                    Follower.follow(this, task.handle, task.username, JOB_RECHECK_MS, log)
                }
                "unfollow" -> {
                    show("Unfollowing @${task.username}…")
                    Unfollower.unfollow(this, task.handle, task.username, log)
                }
                // A newer server can ask for something this app can't do yet.
                else -> Follower.Outcome(Messenger.UNEXPECTED_PAGE,
                    "This version of the app can't do '${task.action}' — update the ICREATEFLOW app")
            }
            if (out.status == Follower.DEVICE_UNAVAILABLE) Follower.forgetIdentity()
            val reported = report(token, device, task.id, out)
            val s = FollowJobs._state.value
            FollowJobs._state.value = s.copy(
                done = s.done + if (out.success && reported) 1 else 0,
                last = "@${task.username} · ${words(out.status)}" + if (reported) "" else " (not reported)",
            )
            delay(BETWEEN_MS)
        }
    }

    /** Reports the outcome; a few tries, because the follow already happened. */
    private suspend fun report(token: String, device: String, id: Int, out: Follower.Outcome): Boolean {
        repeat(3) { attempt ->
            try {
                Api.reportTask(token, device, id, out.status, out.error, out.detail)
                return true
            } catch (e: Api.ApiError) {
                // 409: the server gave up waiting and the follow will be
                // retried — it will find "already following" and finish then.
                if (e.status == 409 || e.status == 401) return false
                if (attempt < 2) delay(RETRY_MS)
            }
        }
        return false
    }

    private fun words(status: String) = when (status) {
        Follower.SENT -> "done"
        Follower.ALREADY_FOLLOWING -> "already followed"
        Unfollower.NOT_FOLLOWING -> "wasn't followed — nothing pressed"
        Follower.FOLLOW_REQUESTED -> "requested"
        Follower.FOLLOW_LIMITED, Follower.FOLLOW_DISCARDED -> "TikTok's follow limit"
        Follower.DEVICE_UNAVAILABLE -> "phone couldn't do it"
        Follower.CHALLENGE_REQUIRED -> "TikTok wants a puzzle solved"
        Follower.PROFILE_UNAVAILABLE -> "profile not found"
        Follower.MESSAGING_UNAVAILABLE -> "doesn't take messages"
        Messenger.MESSAGE_REFUSED -> "TikTok refused the message"
        Follower.RATE_LIMITED -> "TikTok's limit — the campaign waits it out"
        else -> "failed"
    }

    private fun channel() {
        val nm = getSystemService(NotificationManager::class.java)
        if (nm.getNotificationChannel(CHANNEL) == null) {
            nm.createNotificationChannel(NotificationChannel(CHANNEL, "Campaign work", NotificationManager.IMPORTANCE_LOW)
                .apply { description = "Shown while this phone does follows and messages for your campaigns" })
        }
    }

    private fun notification(line: String): Notification {
        val open = PendingIntent.getActivity(this, 0,
            Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT),
            PendingIntent.FLAG_IMMUTABLE)
        return Notification.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat_follow)
            .setContentTitle("Working for your campaigns")
            .setContentText(line)
            .setContentIntent(open)
            .setOngoing(true)
            .build()
    }

    companion object {
        private const val CHANNEL = "follows"
        private const val NOTE_ID = 7
        private const val POLL_MS = 5_000L
        private const val RETRY_MS = 15_000L
        private const val BETWEEN_MS = 2_000L
        /** A job's reopen comes quickly; the server paces follows, not this. */
        private const val JOB_RECHECK_MS = 3_000L
    }
}
