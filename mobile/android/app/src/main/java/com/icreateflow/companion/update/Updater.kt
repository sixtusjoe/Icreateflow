package com.icreateflow.companion.update

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.os.Build
import android.util.Log
import com.icreateflow.companion.BuildConfig
import com.icreateflow.companion.MainActivity
import com.icreateflow.companion.R
import com.icreateflow.companion.data.Api
import com.icreateflow.companion.engine.FollowJobs
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

/**
 * Updates without the Play Store. The server publishes the newest build
 * (`/api/public/app/<package>`, written by deploy/publish-app.sh); on open
 * the app asks, downloads anything newer, checks it against the published
 * SHA-256 and hands it to Android's installer.
 *
 * Android decides how quiet that can be. The first update always asks the
 * person to confirm (and, once, to allow installs from this app). After an
 * update the app has installed itself, Android 12+ lets later ones go
 * through without asking. Nothing here can skip that — and it shouldn't.
 *
 * It installs on its own only when the phone isn't doing campaign work:
 * an install replaces the running app, which would cut a follow off
 * half-way. Then it waits with an "Update now" for the person to choose.
 */
object Updater {
    enum class Phase { Idle, Checking, UpToDate, Downloading, Ready, Installing, Failed }

    data class State(
        val phase: Phase = Phase.Idle,
        val release: Release? = null,
        /** 0..1 while downloading. */
        val progress: Float = 0f,
        val error: String? = null,
    )

    @Serializable
    data class Release(
        @SerialName("version_code") val versionCode: Int,
        @SerialName("version_name") val versionName: String = "",
        val notes: String = "",
        val sha256: String = "",
        val size: Long = 0,
        val url: String,
    )

    val state: StateFlow<State> get() = _state
    private val _state = MutableStateFlow(State())

    private val json = Json { ignoreUnknownKeys = true; coerceInputValues = true }
    private val http = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .build()
    private val once = Mutex()
    private var lastCheck = 0L
    private var file: File? = null

    /** Opening the app many times an hour shouldn't ask the server each time. */
    private const val RECHECK_MS = 10 * 60_000L
    private const val TAG = "IcfUpdate"
    internal const val ACTION_STATUS = "com.icreateflow.companion.UPDATE_STATUS"

    /**
     * Check, download, and install when nothing is running. Safe to call on
     * every resume: it does nothing while a run is under way or for ten
     * minutes after the last check, unless `force` (the Account screen's
     * "Check for updates").
     */
    suspend fun run(ctx: Context, force: Boolean = false) {
        if (!once.tryLock()) return
        try {
            val now = System.currentTimeMillis()
            val s = _state.value.phase
            if (s == Phase.Ready || s == Phase.Installing) {
                if (s == Phase.Ready && !FollowJobs.state.value.on) install(ctx)
                return
            }
            if (!force && now - lastCheck < RECHECK_MS) return
            lastCheck = now
            _state.value = State(Phase.Checking)
            val r = latest()
            if (r == null || r.versionCode <= BuildConfig.VERSION_CODE) {
                _state.value = State(Phase.UpToDate, r)
                return
            }
            _state.value = State(Phase.Downloading, r)
            file = download(ctx, r)
            _state.value = State(Phase.Ready, r)
            if (!FollowJobs.state.value.on) install(ctx)
        } catch (e: Exception) {
            Log.w(TAG, "update failed", e)
            _state.value = _state.value.copy(phase = Phase.Failed, error = e.message ?: "The update didn't download.")
        } finally {
            once.unlock()
        }
    }

    /** "Update now": install what's downloaded, whatever else is going on. */
    fun installNow(ctx: Context) {
        askedToAllow = false
        if (_state.value.phase == Phase.Ready || _state.value.phase == Phase.Failed && file != null) install(ctx)
    }

    /** The newest published build, or null when none is (404). */
    private suspend fun latest(): Release? = withContext(Dispatchers.IO) {
        val req = Request.Builder().url("${Api.base}/api/public/app/${BuildConfig.APPLICATION_ID}").build()
        http.newCall(req).execute().use { res ->
            if (res.code == 404) return@withContext null
            if (!res.isSuccessful) error("The update check failed (${res.code}).")
            json.decodeFromString(Release.serializer(), res.body!!.string())
        }
    }

    private suspend fun download(ctx: Context, r: Release): File = withContext(Dispatchers.IO) {
        val dir = File(ctx.cacheDir, "updates").apply { mkdirs() }
        val out = File(dir, "${r.versionCode}.apk")
        // Downloaded already (an earlier open) and intact: no second trip.
        if (out.isFile && (r.sha256.isEmpty() || sha256(out) == r.sha256.lowercase())) return@withContext out
        dir.listFiles()?.forEach { it.delete() }
        val part = File(dir, "${r.versionCode}.part")
        val url = if (r.url.startsWith("http")) r.url else Api.base + r.url
        http.newCall(Request.Builder().url(url).build()).execute().use { res ->
            if (!res.isSuccessful) error("The update didn't download (${res.code}).")
            val body = res.body!!
            val total = body.contentLength().takeIf { it > 0 } ?: r.size
            body.byteStream().use { input ->
                part.outputStream().use { output ->
                    val buf = ByteArray(64 * 1024)
                    var done = 0L
                    while (true) {
                        val n = input.read(buf)
                        if (n < 0) break
                        output.write(buf, 0, n)
                        done += n
                        if (total > 0) _state.value = _state.value.copy(progress = (done.toFloat() / total).coerceIn(0f, 1f))
                    }
                }
            }
        }
        // Never hand Android a file that isn't the one published.
        if (r.sha256.isNotEmpty() && sha256(part) != r.sha256.lowercase()) {
            part.delete()
            error("The update came down damaged. It will try again next time the app opens.")
        }
        part.renameTo(out)
        out
    }

    private fun sha256(f: File): String {
        val md = MessageDigest.getInstance("SHA-256")
        f.inputStream().use { input ->
            val buf = ByteArray(64 * 1024)
            while (true) { val n = input.read(buf); if (n < 0) break; md.update(buf, 0, n) }
        }
        return md.digest().joinToString("") { "%02x".format(it) }
    }

    private fun install(ctx: Context) {
        val apk = file ?: return
        // Ask for "install unknown apps" before the install, not during it:
        // left to the installer's own prompt, going to Settings and back
        // can cancel the waiting install (it did on a Galaxy Z Flip3).
        // Back from Settings, the next resume finds it Ready and installs.
        if (Build.VERSION.SDK_INT >= 26 && !ctx.packageManager.canRequestPackageInstalls()) {
            _state.value = _state.value.copy(phase = Phase.Ready,
                error = "Allow installs from ICREATEFLOW, then come back to finish the update.")
            if (!askedToAllow) {
                askedToAllow = true
                openAllowSetting(ctx)
            }
            return
        }
        _state.value = _state.value.copy(phase = Phase.Installing, error = null)
        try {
            val installer = ctx.packageManager.packageInstaller
            val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL).apply {
                setAppPackageName(ctx.packageName)
                // Asks for no confirmation; Android grants that only when it
                // is allowed to (see the class note) and asks otherwise.
                if (Build.VERSION.SDK_INT >= 31) setRequireUserAction(PackageInstaller.SessionParams.USER_ACTION_NOT_REQUIRED)
            }
            val id = installer.createSession(params)
            installer.openSession(id).use { session ->
                session.openWrite("app.apk", 0, apk.length()).use { out ->
                    apk.inputStream().use { it.copyTo(out) }
                    session.fsync(out)
                }
                val status = Intent(ctx, UpdateReceiver::class.java).setAction(ACTION_STATUS)
                val flags = PendingIntent.FLAG_UPDATE_CURRENT or
                    (if (Build.VERSION.SDK_INT >= 31) PendingIntent.FLAG_MUTABLE else 0)
                session.commit(PendingIntent.getBroadcast(ctx, id, status, flags).intentSender)
            }
        } catch (e: Exception) {
            Log.w(TAG, "install failed", e)
            failed(e.message ?: "Android wouldn't take the update.")
        }
    }

    /** Opened by itself once per run of the app; after that only from "Update now". */
    private var askedToAllow = false

    private fun openAllowSetting(ctx: Context) {
        runCatching {
            ctx.startActivity(Intent(android.provider.Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                android.net.Uri.parse("package:${ctx.packageName}")).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        }
    }

    internal fun failed(why: String) {
        _state.value = _state.value.copy(phase = Phase.Failed, error = why)
    }
}

/**
 * Android's answers about an install, and the "you've been updated" note.
 * A self-update ends this process, and Android won't reopen an app by
 * itself, so a notification is how the person learns it worked.
 */
class UpdateReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        when (intent.action) {
            Updater.ACTION_STATUS -> when (val s = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, -999)) {
                PackageInstaller.STATUS_PENDING_USER_ACTION -> {
                    @Suppress("DEPRECATION")
                    val confirm = intent.getParcelableExtra<Intent>(Intent.EXTRA_INTENT) ?: return
                    ctx.startActivity(confirm.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                }
                PackageInstaller.STATUS_SUCCESS -> Unit // this process is about to end
                else -> Updater.failed(
                    if (s == PackageInstaller.STATUS_FAILURE_ABORTED) "The update was cancelled. Tap Update now to try again."
                    else intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE) ?: "Android wouldn't install the update.",
                )
            }
            Intent.ACTION_MY_PACKAGE_REPLACED -> {
                updated(ctx)
                // Campaign work, if it was on: the update ended it.
                FollowJobs.resume(ctx)
            }
        }
    }

    private fun updated(ctx: Context) {
        val nm = ctx.getSystemService(NotificationManager::class.java)
        if (nm.getNotificationChannel(CHANNEL) == null) {
            nm.createNotificationChannel(NotificationChannel(CHANNEL, "App updates", NotificationManager.IMPORTANCE_DEFAULT)
                .apply { description = "Says when ICREATEFLOW has updated itself" })
        }
        val open = PendingIntent.getActivity(ctx, 0, Intent(ctx, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        nm.notify(NOTE_ID, android.app.Notification.Builder(ctx, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat_follow)
            .setContentTitle("ICREATEFLOW updated")
            .setContentText("Now on version ${BuildConfig.VERSION_NAME}. Tap to open.")
            .setContentIntent(open)
            .setAutoCancel(true)
            .build())
    }

    private companion object {
        const val CHANNEL = "updates"
        const val NOTE_ID = 11
    }
}
