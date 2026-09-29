package com.icreateflow.companion.engine

import android.content.Context
import kotlinx.coroutines.delay

/**
 * One direct message, start to finish, answered in the server's own words.
 *
 * Learned by hand on 2026-09-27 (@_lancastarmoon → @sixtusjoe, delivered):
 * the profile's header row has Follow and **Message** side by side; Message
 * opens the chat with a "Message..." box at the bottom; once there is text,
 * an unlabelled send button appears to the right of the emoji button; the
 * sent message then shows as a bubble with exactly its text.
 *
 * So: open the profile, tap its Message, type, tap send — and believe it
 * only when the bubble is there and TikTok says nothing against it.
 */
object Messenger {
    const val MESSAGE_REFUSED = "message_refused"
    const val RATE_LIMITED = Follower.RATE_LIMITED
    const val UNEXPECTED_PAGE = "unexpected_page"

    private const val CHAT_WAIT_MS = 12_000L
    private const val SENT_WAIT_MS = 10_000L
    /** A refusal can arrive a moment after the bubble. */
    private const val SETTLE_MS = 3_000L
    private const val POLL_MS = 700L

    /** Said instead of delivering: the words were refused. */
    private val REFUSED = listOf("violat", "community guidelines", "couldn't be sent", "could not be sent",
        "failed to send", "not sent", "unable to send", "tap to resend", "try resending")
    private val SLOW_DOWN = listOf("sending messages too fast", "too many messages", "slow down",
        "try again later")
    /** The person doesn't take messages from this account. */
    // "Couldn’t message this account … has been suspended" (2026-09-29,
    // @ezeonyiko411): read as "the box didn't take the text" before.
    private val CLOSED = listOf("can't send messages", "cannot send messages", "only friends",
        "only accepts messages", "turned off messages", "can't message", "couldn't message",
        "has been suspended")

    /** The first line on screen matching `needles`, ignoring anything in `except`. */
    private fun has(nodes: List<Node>, needles: List<String>, except: Set<String> = emptySet()): String? =
        nodes.map { it.text.ifBlank { it.desc }.trim() }.firstOrNull { t ->
            // TikTok writes its apostrophes curly (’); the needles are straight.
            t !in except && t.lowercase().replace('\u2019', '\'').let { low -> needles.any { it in low } }
        }

    suspend fun send(
        ctx: Context, me: String, who: String, text: String,
        say: (String, Boolean?) -> Unit = { _, _ -> },
    ): Follower.Outcome {
        fun fail(status: String, error: String, line: String = error): Follower.Outcome {
            say(line, false); return Follower.Outcome(status, error)
        }
        val body = text.trim()
        if (body.isEmpty()) return fail(UNEXPECTED_PAGE, "Nothing to send")

        val svc = FollowService.instance
            ?: return fail(Follower.DEVICE_UNAVAILABLE, "The follow service on the phone is switched off")
        Follower.prepare(ctx, svc, me, say)?.let { return it }

        say("Opening @$who…", null)
        val profile = Follower.open(svc, who)
        when {
            profile.challenge -> return fail(Follower.CHALLENGE_REQUIRED,
                "TikTok on the phone is showing a verification puzzle — solve it on the phone, then resume the campaign")
            profile.loginWall -> { Follower.forgetIdentity(); return fail(Follower.DEVICE_UNAVAILABLE,
                "TikTok on the phone is signed out — sign in to @$me") }
            profile.missing -> return fail(Follower.PROFILE_UNAVAILABLE, "Profile not found", "@$who doesn't exist")
            !sameHandle(profile.handle, who) && profile.feed -> {
                say("TikTok opened its For You feed instead of the profile", false)
                return Follower.feedInstead(who)
            }
            !sameHandle(profile.handle, who) -> return if (svc.snapshot().isEmpty())
                fail(Follower.DEVICE_UNAVAILABLE, "TikTok did not come to the front — the phone will try again shortly")
            else fail(Follower.NAVIGATION_TIMEOUT, "@$who's profile did not load on the phone")
            profile.isSelf -> return fail(Follower.MESSAGING_UNAVAILABLE, "That is this account's own profile")
            // A friend's profile (TikTok's newer layout) has "Send a 👋" and
            // no Message button — and that button *sends a wave* before it
            // opens the chat (tried 2026-09-29 on @yunglabozz: 👋 went out
            // at once). Every person would get a wave they weren't meant to,
            // then the message. It is never pressed; the profile has no
            // other way into the chat (its share menu has none either).
            profile.message == null && svc.snapshot().any { it.label.startsWith("send a") } ->
                return fail(Follower.MESSAGING_UNAVAILABLE,
                    "@$who is a friend on TikTok, and their profile only offers \"Send a 👋\", which " +
                        "sends a wave straight away — not pressed, no message sent")
            profile.message == null -> return fail(Follower.MESSAGING_UNAVAILABLE,
                "@$who's profile has no Message button — they don't take messages from this account")
        }

        say("Opening the chat with @$who…", null)
        if (!svc.tap(profile.message!!.cx, profile.message.cy))
            return fail(Follower.DEVICE_UNAVAILABLE, "Android did not deliver the tap")
        var chat = emptyList<Node>()
        val chatBy = System.currentTimeMillis() + CHAT_WAIT_MS
        while (System.currentTimeMillis() < chatBy) {
            delay(POLL_MS)
            chat = svc.snapshot()
            if (chat.any { it.cls == "EditText" } || has(chat, CLOSED) != null) break
        }
        has(chat, CLOSED)?.let { return fail(Follower.MESSAGING_UNAVAILABLE, "TikTok says: $it") }
        val box = chat.filter { it.cls == "EditText" }.maxByOrNull { it.top }
            ?: return fail(Follower.NAVIGATION_TIMEOUT, "The chat with @$who didn't open")

        // The same words may already be in the thread; only a new bubble counts.
        val before = chat.count { it.text.trim() == body }
        // Nor does a notice that was there already, or the message's own
        // words — a message saying "violates" must not read as a refusal.
        val seen = chat.map { it.text.ifBlank { it.desc }.trim() }.toSet() + body

        say("Typing the message…", null)
        if (!svc.setText(body)) return fail(Follower.DEVICE_UNAVAILABLE, "Couldn't type into TikTok's message box")
        delay(1_000)
        val typed = svc.snapshot()
        val input = typed.filter { it.cls == "EditText" }.maxByOrNull { it.top } ?: box
        if (input.text.trim() != body) return fail(UNEXPECTED_PAGE, "The message box didn't take the text")
        val send = sendButton(typed, input)
            ?: return fail(UNEXPECTED_PAGE, "Couldn't find TikTok's send button")

        say("Sending…", null)
        if (!svc.tap(send.cx, send.cy)) return fail(Follower.DEVICE_UNAVAILABLE, "Android did not deliver the tap")

        var after = emptyList<Node>()
        val sentBy = System.currentTimeMillis() + SENT_WAIT_MS
        while (System.currentTimeMillis() < sentBy) {
            delay(POLL_MS)
            after = svc.snapshot()
            if (after.count { it.text.trim() == body } > before || has(after, REFUSED, seen) != null) break
        }
        if (after.count { it.text.trim() == body } > before) {
            delay(SETTLE_MS)
            after = svc.snapshot()
        }
        has(after, REFUSED, seen)?.let { said ->
            say("TikTok refused it: $said", false)
            return Follower.Outcome(MESSAGE_REFUSED, "TikTok refused the message: $said", mapOf("platform_said" to said))
        }
        has(after, SLOW_DOWN, seen)?.let { said ->
            say("TikTok says slow down: $said", false)
            return Follower.Outcome(RATE_LIMITED, "TikTok says: $said", mapOf("platform_said" to said))
        }
        if (after.count { it.text.trim() == body } <= before)
            return fail(UNEXPECTED_PAGE, "The message didn't appear in the chat after sending")
        say("Sent — the message is in the chat", true)
        return Follower.Outcome(Follower.SENT)
    }

    /**
     * TikTok's send button carries no label. It appears, once there's text,
     * to the right of the emoji button on the input's row — so: a labelled
     * "Send" if TikTok ever adds one, else the rightmost clickable thing on
     * that row that isn't the emoji button.
     */
    private fun sendButton(nodes: List<Node>, input: Node): Node? {
        nodes.firstOrNull { it.desc.equals("send", ignoreCase = true) || it.label == "send" }?.let { return it }
        val rowTop = input.top - 40
        val rowBottom = input.bottom + 40
        return nodes.filter {
            it.left >= input.right - 10 && it.cy in rowTop..rowBottom &&
                !it.desc.contains("emoji", ignoreCase = true) && !it.desc.contains("sticker", ignoreCase = true) &&
                (it.right - it.left) in 40..220
        }.maxByOrNull { it.left }
    }
}
