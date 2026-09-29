package com.icreateflow.companion.engine

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.Context
import android.content.Intent
import android.graphics.Path
import android.net.Uri
import android.provider.Settings
import android.util.Log
import android.view.accessibility.AccessibilityEvent
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlin.coroutines.resume

/**
 * The phone's hands: reads TikTok's screen and taps it.
 *
 * An Accessibility service, because that is the only way one app may act
 * inside another on an unrooted phone. Android sends it events only from
 * TikTok (`res/xml/follow_service.xml`), and `snapshot` reads only a TikTok
 * window — anything else on screen comes back empty. It does nothing on
 * its own: it acts only when the app asks, and every action is a single tap
 * at a place it has just read.
 *
 * The same three moves the adb driver was proven with: open a profile by
 * its link, read the screen, tap a point.
 */
class FollowService : AccessibilityService() {

    override fun onServiceConnected() {
        Log.i(TAG, "connected ${System.identityHashCode(this)}")
        instance = this
        _connected.value = true
    }

    // Only a destroyed service is gone. Android unbinds and re-attaches the
    // same object when something pauses Accessibility services for a moment
    // (a screen read over USB does), without calling onServiceConnected
    // again — so clearing on unbind left the app saying "Starting" forever.
    // And it can bind a fresh copy before the old one is torn down, so only
    // the copy that is current may say the service went away.
    override fun onDestroy() {
        Log.i(TAG, "destroyed ${System.identityHashCode(this)}")
        drop()
        super.onDestroy()
    }

    override fun onUnbind(intent: Intent?): Boolean {
        Log.i(TAG, "unbound ${System.identityHashCode(this)}")
        return super.onUnbind(intent)
    }

    override fun onRebind(intent: Intent?) {
        Log.i(TAG, "rebound ${System.identityHashCode(this)}")
        super.onRebind(intent)
    }

    private fun drop() {
        if (instance !== this) return
        instance = null
        _connected.value = false
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) = Unit
    override fun onInterrupt() = Unit

    /** What TikTok is showing right now, or empty if TikTok is not in front. */
    fun snapshot(): List<Node> {
        val roots = buildList {
            rootInActiveWindow?.let { add(it) }
            windows.forEach { w -> w.root?.let { add(it) } }
        }
        val tiktok = roots.firstOrNull { it.packageName?.toString() in TIKTOK_PACKAGES } ?: return emptyList()
        return flatten(tiktok)
    }

    /** One tap at a point, the way a finger would — the move the adb test proved. */
    suspend fun tap(x: Int, y: Int): Boolean = suspendCancellableCoroutine { cont ->
        val path = Path().apply { moveTo(x.toFloat(), y.toFloat()) }
        val gesture = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0, 60))
            .build()
        val ok = dispatchGesture(gesture, object : GestureResultCallback() {
            override fun onCompleted(g: GestureDescription?) { if (cont.isActive) cont.resume(true) }
            override fun onCancelled(g: GestureDescription?) { if (cont.isActive) cont.resume(false) }
        }, null)
        if (!ok && cont.isActive) cont.resume(false)
    }

    fun back() = performGlobalAction(GLOBAL_ACTION_BACK)

    /**
     * Type into TikTok's text box (the lowest one on screen — the chat's
     * "Message..." box). Set through Accessibility, as a keyboard would
     * fill it; nothing is pasted from the clipboard.
     */
    fun setText(text: String): Boolean {
        val root = windows.mapNotNull { it.root }.firstOrNull { it.packageName?.toString() in TIKTOK_PACKAGES }
            ?: rootInActiveWindow?.takeIf { it.packageName?.toString() in TIKTOK_PACKAGES }
            ?: return false
        val boxes = mutableListOf<android.view.accessibility.AccessibilityNodeInfo>()
        fun walk(n: android.view.accessibility.AccessibilityNodeInfo?, depth: Int) {
            if (n == null || depth > 60) return
            if (n.className?.toString()?.endsWith("EditText") == true && n.isEditable) boxes += n
            for (i in 0 until n.childCount) walk(n.getChild(i), depth + 1)
        }
        walk(root, 0)
        val r = android.graphics.Rect()
        val box = boxes.maxByOrNull { it.getBoundsInScreen(r); r.top } ?: return false
        box.performAction(android.view.accessibility.AccessibilityNodeInfo.ACTION_FOCUS)
        val args = android.os.Bundle().apply {
            putCharSequence(android.view.accessibility.AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text)
        }
        return box.performAction(android.view.accessibility.AccessibilityNodeInfo.ACTION_SET_TEXT, args)
    }

    /** Open a profile in TikTok as a fresh task, so each read is a real reload. */
    fun openProfile(handle: String) {
        val pkg = installedTikTok(this) ?: return
        val intent = Intent(Intent.ACTION_VIEW, Uri.parse("https://www.tiktok.com/@${handle.removePrefix("@")}"))
            .setPackage(pkg)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
        startActivity(intent)
    }

    /**
     * TikTok's own search, with `query` typed in — how a person finds a
     * profile. It opens profiles that a link won't (see `Follower.open`).
     */
    fun openSearch(query: String) {
        val pkg = installedTikTok(this) ?: return
        val intent = Intent(Intent.ACTION_VIEW, Uri.parse("snssdk1233://search?keyword=${Uri.encode(query)}"))
            .setPackage(pkg)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
        startActivity(intent)
    }

    companion object {
        /** `adb logcat -s IcfFollow` — how the Mac reads the phone's state without reading its screen. */
        const val TAG = "IcfFollow"
        val TIKTOK_PACKAGES = setOf("com.zhiliaoapp.musically", "com.ss.android.ugc.trill")

        @Volatile var instance: FollowService? = null
            private set
        private val _connected = MutableStateFlow(false)
        val connected: StateFlow<Boolean> = _connected

        /** Switched on in Settings — true even before Android has bound it. */
        fun isEnabled(ctx: Context): Boolean {
            val list = Settings.Secure.getString(ctx.contentResolver,
                Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES) ?: return false
            val me = "${ctx.packageName}/${FollowService::class.java.name}"
            return list.split(':').any { it.equals(me, ignoreCase = true) }
        }

        fun installedTikTok(ctx: Context): String? = TIKTOK_PACKAGES.firstOrNull {
            runCatching { ctx.packageManager.getPackageInfo(it, 0) }.isSuccess
        }
    }
}
