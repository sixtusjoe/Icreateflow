package com.icreateflow.companion.engine

import android.graphics.Rect
import android.view.accessibility.AccessibilityNodeInfo

/**
 * Reading TikTok's screen — a line-for-line port of `read_profile` in
 * `backend/services/outreach/browser/android_tiktok.py`.
 *
 * That code was written against real `uiautomator dump`s of the TikTok app
 * and its traps are tested there; uiautomator reads the very same
 * accessibility tree this service is handed, so the same rules apply
 * unchanged. Keep the two in step: a fix to one is a fix owed to the other.
 *
 *  - The profile's own button is the first follow control *under the
 *    stats row*. The stats label "Following" sits above it, and suggested
 *    accounts' "Follow back" buttons sit far below.
 *  - Being on your own profile is recognised by what only your own profile
 *    offers ("Private videos", "Create a Story").
 */
data class Node(
    val text: String,
    val desc: String,
    val left: Int, val top: Int, val right: Int, val bottom: Int,
    val cls: String = "",
    val clickable: Boolean = false,
) {
    val label get() = text.trim().lowercase()
    val cx get() = (left + right) / 2
    val cy get() = (top + bottom) / 2
}

/** Every node on the screen, flattened, in tree order. */
fun flatten(root: AccessibilityNodeInfo?): List<Node> {
    val out = ArrayList<Node>(256)
    val r = Rect()
    fun walk(n: AccessibilityNodeInfo?, depth: Int) {
        if (n == null || depth > 60) return
        n.getBoundsInScreen(r)
        out += Node(n.text?.toString().orEmpty(), n.contentDescription?.toString().orEmpty(),
            r.left, r.top, r.right, r.bottom,
            n.className?.toString()?.substringAfterLast('.').orEmpty(), n.isClickable)
        for (i in 0 until n.childCount) walk(n.getChild(i), depth + 1)
    }
    walk(root, 0)
    return out
}

val CAN_FOLLOW = setOf("follow", "follow back")
val FOLLOWING = setOf("following", "friends")
val PENDING = setOf("requested")

private val MISSING = listOf("couldn't find this account")
private val LOGIN_WALL = listOf("log in to tiktok", "sign up for tiktok", "log in or sign up")
private val CHALLENGE = listOf("verify to continue", "drag the slider", "drag the puzzle",
    "select 2 objects", "verification failed")
private val LIMITED = listOf("following too fast", "you are visiting too frequently",
    "too many attempts", "too many requests", "daily limit", "try again later")
private val SELF_MARKERS = setOf("private videos", "create a story", "edit profile")
private const val BUTTON_BAND_PX = 400

private val HANDLE = Regex("@[\\w.]{1,30}")
private val COUNT = Regex("[\\d.,]+[KMB]?")

data class ProfileView(
    val handle: String? = null,
    /** "can_follow" / "following" / "pending" / null */
    val state: String? = null,
    val control: Node? = null,
    /** The profile's own Message button, beside Follow — null when it has none. */
    val message: Node? = null,
    val followers: String? = null,
    val isSelf: Boolean = false,
    val missing: Boolean = false,
    val loginWall: Boolean = false,
    val challenge: Boolean = false,
    val limitNotice: String? = null,
    /**
     * TikTok's home feed ("For You") is showing and no profile is. A link
     * to a profile lands here when TikTok's app fails to look the name up:
     * the same few profiles, every time, while the ones either side open
     * (2026-09-28, @kayceebob1 three times in two days). Search finds them
     * — see `Follower.open`.
     */
    val feed: Boolean = false,
)

private fun has(texts: List<String>, needles: List<String>): String? =
    texts.firstOrNull { t -> val low = t.lowercase(); needles.any { it in low } }

fun readProfile(nodes: List<Node>): ProfileView {
    val texts = nodes.map { it.text }.filter { it.isNotBlank() } + nodes.map { it.desc }.filter { it.isNotBlank() }
    // Verified profiles end the handle with their badge, an invisible
    // U+FFFC (@khaby.lame, 2026-09-28) — unread, every one failed to open.
    val handle = nodes.map { it to it.text.replace(INVISIBLE, "").trim() }
        .filter { (_, t) -> HANDLE.matches(t) }.minByOrNull { (n, _) -> n.top }
        ?.second?.drop(1)

    var state: String? = null
    var control: Node? = null
    var message: Node? = null
    var followers: String? = null
    // "Follower" on a profile with exactly one (@jeffeyrisky, 2026-09-28):
    // missed, it read as a profile with no Follow button.
    val stats = nodes.filter { it.label == "followers" || it.label == "follower" }.minByOrNull { it.top }
    if (stats != null) {
        followers = nodes.filter {
            it.bottom <= stats.top + 8 && it.top >= stats.top - 120 &&
                it.left < stats.right && it.right > stats.left && COUNT.matches(it.text.trim())
        }.maxByOrNull { it.top }?.text?.trim()
        val floor = stats.bottom
        control = nodes.filter {
            (it.label in CAN_FOLLOW || it.label in FOLLOWING || it.label in PENDING) &&
                it.top >= floor && it.top <= floor + BUTTON_BAND_PX
        }.minByOrNull { it.top }
        // Same band as Follow: the header's own row, not a "Message" in a
        // suggested account or a caption further down.
        message = nodes.filter {
            it.label == "message" && it.top >= floor && it.top <= floor + BUTTON_BAND_PX
        }.minByOrNull { it.top }
        state = when (control?.label) {
            null -> null
            in FOLLOWING -> "following"
            in PENDING -> "pending"
            else -> "can_follow"
        }
    }
    return ProfileView(
        handle = handle, state = state, control = control, message = message, followers = followers,
        isSelf = nodes.any { (it.desc.ifBlank { it.text }).trim().lowercase() in SELF_MARKERS },
        missing = has(texts, MISSING) != null,
        loginWall = has(texts, LOGIN_WALL) != null,
        challenge = has(texts, CHALLENGE) != null,
        limitNotice = has(texts, LIMITED),
        // The feed's top tabs, and no profile stats row.
        feed = stats == null && nodes.any { it.label == "for you" } && nodes.any { it.label == "following" },
    )
}

fun sameHandle(a: String?, b: String?) =
    !a.isNullOrBlank() && !b.isNullOrBlank() &&
        plainHandle(a).equals(plainHandle(b), ignoreCase = true)

/**
 * TikTok wraps names in invisible direction marks (U+200E, U+2068…), and a
 * verified badge is an invisible U+FFFC after the name: gone, and the @.
 */
fun plainHandle(s: String) = s.replace(INVISIBLE, "").trim().removePrefix("@")

private val INVISIBLE = Regex("[\\u200b-\\u200f\\u202a-\\u202e\\u2066-\\u2069\\ufffc]")

/**
 * TikTok's search results for `handle`: whether they're showing (the
 * search box holds the name, and the result tabs are up), and the result
 * line whose name is exactly `handle` — never a lookalike.
 */
data class SearchView(val showing: Boolean = false, val hit: Node? = null, val usersTab: Node? = null)

fun readSearch(nodes: List<Node>, handle: String): SearchView {
    val box = nodes.firstOrNull { it.cls.endsWith("EditText") && sameHandle(it.text, handle) }
    val users = nodes.firstOrNull { it.desc.trim().equals("users", ignoreCase = true) }
        ?: nodes.firstOrNull { it.label == "users" }
    if (box == null || users == null) return SearchView()
    val hit = nodes.filter {
        !it.cls.endsWith("EditText") && it.top > users.bottom && sameHandle(it.text, handle)
    }.minByOrNull { it.top }
    return SearchView(showing = true, hit = hit, usersTab = users)
}
