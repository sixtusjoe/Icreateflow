package com.icreateflow.companion.engine

import android.app.KeyguardManager
import android.content.Context
import android.content.Intent
import android.util.Log
import com.icreateflow.companion.MainActivity
import com.icreateflow.companion.data.Api
import com.icreateflow.companion.data.PhoneLead
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.OkHttpClient
import okhttp3.Request
import java.util.concurrent.TimeUnit
import kotlin.random.Random

/**
 * Finding leads in the TikTok app: open each video's comments, open every
 * commenter's profile for the @handle the list doesn't show, and hand each
 * one to the server as it's read.
 *
 * Measured on the Z Flip3 (2026-10-12) before any of this was written:
 *  - A comment row carries only the display name and an avatar — no
 *    @handle anywhere in its tree. The profile has it, with the follower
 *    count; Back returns to the list exactly where it was.
 *  - The video's comment button says "Read or add comments. N comments";
 *    the sheet's header says "N comments". Those words are the anchors —
 *    TikTok's view ids are scrambled and change between versions.
 *  - About three new commenters come into view per swipe. Replies, once
 *    "View N replies" is pressed, read exactly like comments.
 *  - A linked video opens at the top of the For You feed, which can move
 *    on by itself: the comments are opened straight away.
 *
 * Read-only. Nothing is followed, liked or commented — the only taps are
 * the comment button, a name, "View N replies", and Back.
 *
 * The server keeps the books (`/leads/searches/{id}/phone-leads`): who is
 * new, how many are wanted, and whether Stop was pressed. The phone asks
 * with every report, so a Stop on the website stops the phone too.
 */
object PhoneSearch {
    data class State(
        val running: Boolean = false,
        val searchId: Int? = null,
        val line: String = "",
        val found: Int = 0,
        val wanted: Int = 0,
    )

    val state: StateFlow<State> get() = _state
    private val _state = MutableStateFlow(State())
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var job: Job? = null

    private const val SHEET_WAIT_MS = 15_000L
    private const val PROFILE_WAIT_MS = 8_000L
    private const val BACK_WAIT_MS = 5_000L
    private const val POLL_MS = 400L
    /** Rounds in a row with nobody new and nothing to open: the list is spent. */
    private const val QUIET_ROUNDS = 5
    private const val MAX_ROUNDS = 600
    private const val REPLY_TAPS_PER_ROUND = 2

    private val COMMENTS_HEADER = Regex("""^[\d.,]+\s*[KMB]?\s+comments?$""", RegexOption.IGNORE_CASE)
    private val INVISIBLE = Regex("[\\u200b-\\u200f\\u202a-\\u202e\\u2066-\\u2069\\ufffc]")
    private val VIDEO_LINK = Regex("""tiktok\.com/@[^/?]+/video/\d+""", RegexOption.IGNORE_CASE)
    /** Reads where a share link points without following it. */
    private val redirects = OkHttpClient.Builder()
        .followRedirects(false).followSslRedirects(false)
        .connectTimeout(10, TimeUnit.SECONDS).readTimeout(10, TimeUnit.SECONDS)
        .build()

    fun stop() { job?.cancel() }

    /** Start reading `videos` for search `searchId`; returns false if one is already going. */
    fun start(ctx: Context, token: String, searchId: Int, videos: List<String>, wanted: Int, replies: Boolean): Boolean {
        if (_state.value.running || FollowJobs.state.value.on) return false
        val app = ctx.applicationContext
        _state.value = State(true, searchId, "Starting…", 0, wanted)
        // A search runs for minutes: a screen left to time out locks the
        // phone and stops the reading, as campaign work found before.
        @Suppress("DEPRECATION")
        val wake = app.getSystemService(android.os.PowerManager::class.java)
            .newWakeLock(android.os.PowerManager.SCREEN_DIM_WAKE_LOCK, "icf:search")
            .apply { acquire(60 * 60_000L) }
        job = scope.launch {
            val (status, message) = try {
                run(app, token, searchId, videos, replies)
            } catch (e: kotlinx.coroutines.CancellationException) {
                "cancelled" to "Stopped on the phone — ${_state.value.found} profile(s) kept."
            } catch (e: Exception) {
                Log.w(FollowService.TAG, "phone search failed", e)
                "failed" to "The phone stopped: ${e.message ?: "something went wrong"}"
            }
            say(message)
            if (wake.isHeld) wake.release()
            // On its own scope: this one may be cancelled.
            CoroutineScope(Dispatchers.Main).launch {
                runCatching { Api.finishPhoneSearch(token, searchId, status, message) }
                _state.value = _state.value.copy(running = false)
                app.startActivity(Intent(app, MainActivity::class.java)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_REORDER_TO_FRONT))
            }
        }
        return true
    }

    private fun say(line: String, found: Int = _state.value.found) {
        Log.i(FollowService.TAG, "search: $line")
        _state.value = _state.value.copy(line = line, found = found)
    }

    /** The whole search; returns how it ended, in the server's words. */
    private suspend fun run(ctx: Context, token: String, searchId: Int, videos: List<String>, replies: Boolean): Pair<String, String> {
        val svc = FollowService.instance ?: return "failed" to "The phone service is off — turn it on in the app's Phone tab."
        if (FollowService.installedTikTok(ctx) == null) return "failed" to "TikTok isn't installed on this phone."
        if (ctx.getSystemService(KeyguardManager::class.java)?.isKeyguardLocked == true)
            return "failed" to "The phone was locked, so nothing was read. Unlock it and start again."

        // Display names already opened this run, so someone who commented
        // twice costs one profile visit, not two.
        val opened = HashSet<String>()
        var stop = false
        videos.forEachIndexed { i, url ->
            if (stop) return@forEachIndexed
            val label = if (videos.size > 1) "video ${i + 1} of ${videos.size}" else "the video"
            say("Opening $label…")
            stop = readVideo(svc, token, searchId, url, label, replies, opened)
        }
        val found = _state.value.found
        return if (stop && found >= _state.value.wanted) "done" to "Found the $found profiles asked for, on the phone."
        else "done" to "Read every comment it could reach — $found new profile(s)."
    }

    /** One video, top to bottom. True when the search should end (enough found, or stopped). */
    private suspend fun readVideo(
        svc: FollowService, token: String, searchId: Int, url: String, label: String, replies: Boolean,
        opened: MutableSet<String>,
    ): Boolean {
        svc.openLink(fullLink(url))
        // The comment button, as soon as the video is up — the feed can move on.
        var button: Node? = null
        val until = System.currentTimeMillis() + SHEET_WAIT_MS
        while (button == null && System.currentTimeMillis() < until) {
            delay(POLL_MS)
            val nodes = svc.snapshot()
            checkBlocked(nodes)
            button = nodes.filter { it.desc.trim().lowercase().startsWith("read or add comments") }
                .minByOrNull { kotlin.math.abs(it.cy - 1650) }
        }
        if (button == null) { say("$label didn't open in TikTok — skipping it"); return false }
        svc.tap(button.cx, button.cy)

        var header: Node? = null
        val sheetUntil = System.currentTimeMillis() + SHEET_WAIT_MS
        while (header == null && System.currentTimeMillis() < sheetUntil) {
            delay(POLL_MS)
            header = header(svc.snapshot())
        }
        if (header == null) { say("The comments on $label didn't open — skipping it"); return false }
        say("Reading the comments on $label")

        var quiet = 0
        var rounds = 0
        val expanded = HashSet<String>()
        while (quiet < QUIET_ROUNDS && rounds < MAX_ROUNDS) {
            rounds++
            val nodes = svc.snapshot()
            checkBlocked(nodes)
            val top = header(nodes)?.bottom ?: return false.also { say("The comments closed on $label — moving on") }
            val floor = nodes.firstOrNull { it.cls.endsWith("EditText") }?.top ?: (top + 1200)
            var progressed = false

            for (name in names(nodes, top, floor)) {
                val key = clean(name.text)
                if (!opened.add(key)) continue
                progressed = true
                val lead = openAndRead(svc, name, top) ?: continue
                val res = runCatching {
                    Api.reportPhoneLeads(token, searchId, listOf(lead.copy(source = url)),
                        "Reading the comments on $label")
                }.getOrNull()
                if (res != null) {
                    say(if (res.taken.isNotEmpty()) "Found @${lead.username}" else "@${lead.username} is already known", res.found)
                    if (res.stop) return true
                }
                // A person's pace between profiles, not a machine's.
                delay(Random.nextLong(500, 1300))
                // The list may have shifted under the next name: read it again.
                break
            }
            if (progressed) { quiet = 0; continue }

            if (replies) {
                val more = nodes.filter {
                    val l = clean(it.text).lowercase()
                    it.top > top && it.bottom < floor && l.startsWith("view ") && "repl" in l &&
                        expandKey(nodes, it) !in expanded
                }.take(REPLY_TAPS_PER_ROUND)
                if (more.isNotEmpty()) {
                    more.forEach { expanded += expandKey(nodes, it); svc.tap(it.cx, it.cy); delay(900) }
                    quiet = 0
                    continue
                }
            }

            // Nothing new on screen: scroll on, and check in with the server
            // now and then, so a Stop pressed elsewhere is heard.
            svc.swipe(540, floor - 150, 540, top + 300)
            delay(1_100)
            if (rounds % 8 == 0) {
                val res = runCatching { Api.reportPhoneLeads(token, searchId, emptyList(), "Reading the comments on $label") }.getOrNull()
                if (res?.stop == true) return true
            }
            if (names(svc.snapshot(), top, floor).all { clean(it.text) in opened }) quiet++ else quiet = 0
        }
        return false
    }

    /**
     * A share link (vm.tiktok.com/…, tiktok.com/t/…) as the video's own
     * link. TikTok opens a share link as a random For You video with the
     * shared one in a small card on top, and the comment button found is
     * the one underneath — measured 2026-10-18. The full link opens the
     * video itself. The link as given when it can't be worked out.
     */
    private suspend fun fullLink(url: String): String = withContext(Dispatchers.IO) {
        if (VIDEO_LINK.containsMatchIn(url)) return@withContext url
        var at = url
        repeat(4) {
            val next = runCatching {
                redirects.newCall(Request.Builder().url(at).head().build()).execute()
                    .use { res -> res.header("Location")?.let { at.toHttpUrl().resolve(it)?.toString() } }
            }.getOrNull() ?: return@withContext url
            if (VIDEO_LINK.containsMatchIn(next)) return@withContext next.substringBefore('?')
            at = next
        }
        url
    }

    /** The sheet's "330 comments" header, or null when the sheet isn't up. */
    private fun header(nodes: List<Node>): Node? =
        nodes.firstOrNull { COMMENTS_HEADER.matches(clean(it.text)) }

    /**
     * Commenters' names on screen, top to bottom: the clickable text that
     * heads each comment. Not "Reply", not "View N replies", and only in
     * the left part of the sheet, where names start (replies are indented).
     */
    private fun names(nodes: List<Node>, top: Int, floor: Int): List<Node> = nodes.filter {
        val l = clean(it.text).lowercase()
        it.clickable && it.cls == "Button" && l.isNotEmpty() && it.top > top && it.bottom < floor &&
            it.left in 100..450 && l != "reply" && !l.startsWith("view ") && !l.startsWith("hide")
    }.sortedBy { it.top }

    /** A reply control is known by the comment it hangs under, since "View 1 reply" repeats. */
    private fun expandKey(nodes: List<Node>, control: Node): String {
        val owner = nodes.filter { it.cls == "Button" && it.clickable && it.bottom <= control.top && it.left in 100..450 }
            .maxByOrNull { it.top }
        return clean(owner?.text.orEmpty()) + "|" + clean(control.text)
    }

    /** Tap a name, read the profile it opens, come back. Null if no handle could be read. */
    private suspend fun openAndRead(svc: FollowService, name: Node, sheetTop: Int): PhoneLead? {
        svc.tap(name.cx, name.cy)
        var view = ProfileView()
        val until = System.currentTimeMillis() + PROFILE_WAIT_MS
        while (System.currentTimeMillis() < until) {
            delay(POLL_MS)
            val nodes = svc.snapshot()
            checkBlocked(nodes, profile = true)
            view = readProfile(nodes)
            if (view.handle != null && (view.state != null || view.isSelf || view.followers != null)) break
        }
        // Back to the list, and make sure it is the list.
        if (header(svc.snapshot()) == null) {
            svc.back()
            val back = System.currentTimeMillis() + BACK_WAIT_MS
            while (header(svc.snapshot()) == null && System.currentTimeMillis() < back) delay(POLL_MS)
        }
        val handle = view.handle ?: return null
        if (view.isSelf) return null
        return PhoneLead(username = handle, displayName = clean(name.text), followers = count(view.followers))
    }

    /** TikTok asking for a puzzle, or saying slow down: stop here, honestly. */
    // "Slow down" only on a profile page: in a comment list the same words
    // are just somebody's comment.
    private fun checkBlocked(nodes: List<Node>, profile: Boolean = false) {
        val v = readProfile(nodes)
        if (v.challenge) error("TikTok is showing a verification puzzle — solve it on the phone, then search again.")
        if (profile) v.limitNotice?.let { error("TikTok said \"$it\" — try again later.") }
        if (v.loginWall) error("TikTok on the phone is signed out.")
    }

    private fun clean(s: String) = s.replace(INVISIBLE, "").trim()

    /** "951" → 951, "12.3K" → 12300, "1.2M" → 1200000. */
    internal fun count(s: String?): Int? {
        val t = s?.trim()?.replace(",", "")?.uppercase() ?: return null
        val mult = when (t.lastOrNull()) { 'K' -> 1_000.0; 'M' -> 1_000_000.0; 'B' -> 1_000_000_000.0; else -> 1.0 }
        val n = (if (mult > 1) t.dropLast(1) else t).toDoubleOrNull() ?: return null
        return (n * mult).toInt()
    }
}
