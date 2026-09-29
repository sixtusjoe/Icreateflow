package com.icreateflow.companion.ui

import android.content.Intent
import android.net.Uri
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.automirrored.outlined.OpenInNew
import androidx.compose.material.icons.rounded.Pause
import androidx.compose.material.icons.rounded.PlayArrow
import androidx.compose.material.icons.rounded.Stop
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.TextButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.icreateflow.companion.data.Api
import com.icreateflow.companion.data.Campaign
import com.icreateflow.companion.data.CampaignDetail
import com.icreateflow.companion.data.Target
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.time.Duration
import java.time.OffsetDateTime

/**
 * One campaign: where it stands, and every person in it.
 *
 * Both halves come from endpoints the website already uses — the campaign
 * detail for the figures, and the paged target list for the people. The
 * list is paged, 25 to a page with Previous / Next, like the website's
 * pager: a campaign can hold thousands, and a page number says where in
 * them you are, which an endless scroll does not.
 *
 * Tapping a person opens their profile in the TikTok or Instagram app, so
 * a result can be checked by eye — the same distrust of our own reporting
 * the drivers are built on.
 */
@Composable
fun CampaignScreen(token: String, id: Int, onBack: () -> Unit, onSignedOut: () -> Unit) {
    val t = LocalTokens.current
    BackHandler(onBack = onBack)
    var detail by remember { mutableStateOf<CampaignDetail?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var tab by remember { mutableStateOf<String?>(null) }
    var targets by remember { mutableStateOf<List<Target>>(emptyList()) }
    var total by remember { mutableIntStateOf(0) }
    var page by remember { mutableIntStateOf(0) }
    var loadingPage by remember { mutableStateOf(false) }
    var acting by remember { mutableStateOf(false) }
    var actionError by remember { mutableStateOf<String?>(null) }
    var confirmStop by remember { mutableStateOf(false) }
    var confirmEarly by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()

    suspend fun loadDetail() {
        try { detail = Api.campaign(token, id); error = null }
        catch (e: Api.ApiError) { if (e.status == 401) onSignedOut() else error = e.message }
    }

    suspend fun loadPage() {
        loadingPage = true
        try {
            val res = Api.targets(token, id, tab, page * PAGE_SIZE, PAGE_SIZE)
            targets = res.targets
            total = if (tab == null) res.total else res.counts[tab] ?: 0
        } catch (e: Api.ApiError) {
            if (e.status == 401) onSignedOut() else error = e.message
        } finally { loadingPage = false }
    }

    fun act(action: String) {
        if (acting) return
        acting = true; actionError = null
        scope.launch {
            try {
                Api.control(token, id, action)
                loadDetail(); loadPage()
            } catch (e: Api.ApiError) {
                if (e.status == 401) onSignedOut() else actionError = e.message
            } finally { acting = false }
        }
    }

    LaunchedEffect(id) { while (true) { loadDetail(); delay(15_000) } }
    LaunchedEffect(id, tab, page) { loadPage() }

    val c = detail?.campaign
    val listState = androidx.compose.foundation.lazy.rememberLazyListState()
    // The "People" heading's position: back link, header, controls, the
    // message when shown, outcomes when shown.
    val peopleIndex = 3 + (if (c != null && c.activity == "message" && !c.messageTemplate.isNullOrBlank()) 1 else 0) + if (c != null && c.activity in setOf("follow", "unfollow") &&
        detail!!.successOutcomes.isNotEmpty()) 1 else 0
    var paged by remember { mutableStateOf(false) }
    LaunchedEffect(page) {
        // A new page starts at its top, not wherever the last one was left.
        if (paged) listState.animateScrollToItem(peopleIndex)
        paged = true
    }
    LazyColumn(
        Modifier.fillMaxSize(),
        state = listState,
        contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 4.dp, bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            Row(
                Modifier.clip(RoundedCornerShape(10.dp)).clickable(onClick = onBack).padding(vertical = 6.dp, horizontal = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(Icons.AutoMirrored.Outlined.ArrowBack, null, Modifier.size(18.dp), tint = t.inkMuted)
                Spacer(Modifier.width(6.dp))
                Text("All campaigns", style = Type.small, color = t.inkMuted)
            }
        }
        if (c == null) {
            item {
                Text(error ?: "Loading…", style = Type.body, color = if (error != null) t.bad else t.inkMuted,
                    modifier = Modifier.padding(4.dp))
            }
            return@LazyColumn
        }
        item { Header(c) }
        item {
            // Resuming ends a platform cooldown early. Allowed — the website
            // allows it — but asked about, since the platform set it.
            val cooling = c.pausedUntil?.let { resumesIn(it) }?.takeIf { it.startsWith("back in") }
            Controls(c.status, acting, actionError,
                onAct = { if (it == "resume" && cooling != null) confirmEarly = cooling else act(it) },
                onStop = { confirmStop = true })
        }
        if (c.activity == "message" && !c.messageTemplate.isNullOrBlank()) item { MessageCard(c) }
        val outcomes = detail!!.successOutcomes
        if (c.activity in setOf("follow", "unfollow") && outcomes.isNotEmpty()) item { Outcomes(c.activity, outcomes) }
        item {
            Text("PEOPLE", style = Type.label, color = t.inkSubtle, modifier = Modifier.padding(start = 4.dp, top = 6.dp))
        }
        item { StatusTabs(tab, detail!!.targetCounts) { tab = it; page = 0 } }
        if (targets.isEmpty() && !loadingPage) {
            item {
                Sheet(Modifier.fillMaxWidth()) {
                    Text("No one here", style = Type.cardTitle, color = t.ink)
                    Text(if (tab == null) "This campaign has no targets yet." else "No targets are ${tab}.",
                        style = Type.small, color = t.inkMuted)
                }
            }
        } else {
            item { TargetList(targets, c.activity, c.status == "running") }
        }
        if (total > PAGE_SIZE) {
            item {
                Pager(page, total, loadingPage, onPrev = { page -= 1 }, onNext = { page += 1 })
            }
        }
    }
    confirmEarly?.let { left ->
        val platform = PLATFORM_LABEL[detail?.campaign?.platform] ?: "The platform"
        AlertDialog(
            onDismissRequest = { confirmEarly = null },
            containerColor = t.card,
            title = { Text("Resume before the limit resets?", style = Type.title, color = t.ink) },
            text = {
                Text("$platform limited this account; it's due $left. Resuming now usually hits the same " +
                    "limit and pauses again.", style = Type.body, color = t.inkMuted)
            },
            confirmButton = {
                TextButton(onClick = { confirmEarly = null; act("resume") }) { Text("Resume now", style = Type.cardTitle, color = t.ink) }
            },
            dismissButton = {
                TextButton(onClick = { confirmEarly = null }) { Text("Wait", style = Type.cardTitle, color = t.ink) }
            },
        )
    }
    if (confirmStop) {
        AlertDialog(
            onDismissRequest = { confirmStop = false },
            containerColor = t.card,
            title = { Text("Stop this campaign?", style = Type.title, color = t.ink) },
            text = {
                Text("The run ends now. Nobody is lost — everyone not yet reached waits, and Start picks up " +
                    "where it stopped. Use Pause if you just want a break.", style = Type.body, color = t.inkMuted)
            },
            confirmButton = {
                TextButton(onClick = { confirmStop = false; act("stop") }) { Text("Stop", style = Type.cardTitle, color = t.bad) }
            },
            dismissButton = {
                TextButton(onClick = { confirmStop = false }) { Text("Keep it", style = Type.cardTitle, color = t.ink) }
            },
        )
    }
}

/**
 * The website's run buttons, by status: Start for a campaign that isn't
 * going, Pause and Stop while it runs, Resume and Stop while it's paused.
 * Starting and resuming clear a platform cooldown — the website does the
 * same, on the operator's say-so — so the hint says so when there is one.
 */
@Composable
private fun Controls(status: String, busy: Boolean, error: String?, onAct: (String) -> Unit, onStop: () -> Unit) {
    val t = LocalTokens.current
    Column {
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            when (status) {
                "running" -> {
                    RunButton("Pause", Icons.Rounded.Pause, primary = false, busy = busy, Modifier.weight(1f)) { onAct("pause") }
                    RunButton("Stop", Icons.Rounded.Stop, primary = true, busy = busy, Modifier.weight(1f), onStop)
                }
                "paused" -> {
                    RunButton("Stop", Icons.Rounded.Stop, primary = false, busy = busy, Modifier.weight(1f), onStop)
                    RunButton("Resume", Icons.Rounded.PlayArrow, primary = true, busy = busy, Modifier.weight(1f)) { onAct("resume") }
                }
                else -> RunButton("Start campaign", Icons.Rounded.PlayArrow, primary = true, busy = busy, Modifier.weight(1f)) { onAct("start") }
            }
        }
        if (error != null) {
            Spacer(Modifier.height(10.dp))
            Box(
                Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(t.bad.copy(alpha = 0.08f)).padding(12.dp),
            ) { Text(error, style = Type.small, color = t.ink) }
        }
    }
}

@Composable
private fun RunButton(
    label: String, icon: androidx.compose.ui.graphics.vector.ImageVector, primary: Boolean, busy: Boolean,
    modifier: Modifier, onClick: () -> Unit,
) {
    val t = LocalTokens.current
    val shape = RoundedCornerShape(50)
    Row(
        modifier.height(48.dp).clip(shape)
            .background(if (primary) t.primary else t.card)
            .border(1.dp, if (primary) t.primary else t.border, shape)
            .clickable(enabled = !busy, onClick = onClick),
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        val fg = if (primary) t.onPrimary else t.ink
        if (busy) CircularProgressIndicator(Modifier.size(16.dp), color = fg.copy(alpha = 0.6f), strokeWidth = 2.dp)
        else Icon(icon, null, Modifier.size(18.dp), tint = fg)
        Spacer(Modifier.width(8.dp))
        Text(label, style = Type.cardTitle, color = fg)
    }
}

@Composable
private fun Header(c: Campaign) {
    val t = LocalTokens.current
    val (word, tone) = campaignStatus(c)
    val fraction = if (c.totalTargets > 0) c.processed.toFloat() / c.totalTargets else 0f
    Sheet(Modifier.fillMaxWidth(), padding = 18) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            PlatformTile(c.platform, 40)
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(c.name, style = Type.title, color = t.ink, maxLines = 2, overflow = TextOverflow.Ellipsis)
                Spacer(Modifier.height(4.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    TaskChip(c.activity)
                    Spacer(Modifier.width(6.dp))
                    Text(PLATFORM_LABEL[c.platform] ?: c.platform, style = Type.small, color = t.inkSubtle)
                }
            }
        }
        Spacer(Modifier.height(14.dp))
        StatusPill(word, tone)
        Spacer(Modifier.height(16.dp))
        Row(verticalAlignment = Alignment.Bottom) {
            Text(groupThousands(c.processed), style = Type.figure, color = t.ink)
            Text(" / ${groupThousands(c.totalTargets)}", style = Type.title, color = t.inkSubtle)
            Spacer(Modifier.weight(1f))
            Text("${(fraction * 100).toInt()}% worked", style = Type.small, color = t.inkMuted)
        }
        Spacer(Modifier.height(10.dp))
        Progress(fraction)
        Spacer(Modifier.height(14.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(20.dp)) {
            Fig("SUCCEEDED", c.successful)
            Fig("FAILED", c.failed)
            Fig("LEFT", (c.totalTargets - c.processed).coerceAtLeast(0))
        }
        val reason = c.pausedReason
        if (c.status == "paused" && !reason.isNullOrBlank()) {
            Spacer(Modifier.height(14.dp))
            Box(
                Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp))
                    .background((if (tone == Tone.Bad) t.bad else t.warn).copy(alpha = 0.08f))
                    .padding(12.dp),
            ) { Text(reason, style = Type.small, color = t.inkMuted) }
        }
    }
}

@Composable
private fun Fig(label: String, v: Int) {
    val t = LocalTokens.current
    Column {
        Text(groupThousands(v), style = Type.cardTitle, color = t.ink)
        Text(label, style = Type.label, color = t.inkSubtle)
    }
}

/**
 * What a message campaign sends. Shown as written — the {{placeholders}}
 * are filled in per person when it goes out, on the phone or the browser.
 */
@Composable
private fun MessageCard(c: Campaign) {
    val t = LocalTokens.current
    Sheet(Modifier.fillMaxWidth()) {
        Text("THE MESSAGE", style = Type.label, color = t.inkSubtle)
        Spacer(Modifier.height(10.dp))
        Box(
            Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(t.tile).padding(14.dp),
        ) { Text(c.messageTemplate.orEmpty(), style = Type.body, color = t.ink) }
        if (c.hasAttachment) {
            Spacer(Modifier.height(8.dp))
            Text("Sent with an image — only accounts on the browser can send this one.",
                style = Type.small, color = t.inkSubtle)
        }
        if (c.messageRefused) {
            Spacer(Modifier.height(8.dp))
            Text("TikTok refused this wording. Change it on the website before resuming.",
                style = Type.small, color = t.bad)
        }
    }
}

/**
 * What the successes actually were. A follow campaign's "succeeded" mixes
 * real follows with profiles already followed and requests awaiting a
 * person — the website shows the split for the same reason: only the first
 * moves the account's following count.
 */
@Composable
private fun Outcomes(activity: String, o: Map<String, Int>) {
    val t = LocalTokens.current
    val rows = if (activity == "unfollow") listOf(
        "Unfollowed" to (o["sent"] ?: 0),
        "Weren't followed" to (o["not_following"] ?: 0),
    ) else listOf(
        "Followed" to (o["sent"] ?: 0),
        "Already followed" to (o["already_following"] ?: 0),
        "Requested" to (o["follow_requested"] ?: 0),
    )
    Sheet(Modifier.fillMaxWidth()) {
        Text("WHAT THE SUCCESSES WERE", style = Type.label, color = t.inkSubtle)
        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(20.dp)) {
            rows.forEach { (label, n) ->
                Column {
                    Text(groupThousands(n), style = Type.cardTitle, color = t.ink)
                    Text(label, style = Type.small, color = t.inkMuted)
                }
            }
        }
    }
}

private val TABS = listOf(null to "All", "queued" to "Queued", "sent" to "Done", "failed" to "Failed", "skipped" to "Skipped", "paused" to "Waiting")

@Composable
private fun StatusTabs(current: String?, counts: Map<String, Int>, onPick: (String?) -> Unit) {
    val t = LocalTokens.current
    Row(
        Modifier.horizontalScroll(rememberScrollState()).clip(RoundedCornerShape(12.dp))
            .background(t.card).border(1.dp, t.border, RoundedCornerShape(12.dp)).padding(3.dp),
        horizontalArrangement = Arrangement.spacedBy(3.dp),
    ) {
        // An empty status is noise — except the one you're on.
        TABS.filter { (key, _) -> key == null || key == current || (counts[key] ?: 0) > 0 }.forEach { (key, label) ->
            val on = key == current
            val n = if (key == null) counts.values.sum() else counts[key] ?: 0
            Row(
                Modifier.clip(RoundedCornerShape(9.dp)).background(if (on) t.primary else t.card)
                    .clickable { onPick(key) }.padding(horizontal = 12.dp, vertical = 7.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(label, style = Type.small, color = if (on) t.onPrimary else t.inkMuted)
                Spacer(Modifier.width(5.dp))
                Text(groupThousands(n), style = Type.label, color = if (on) t.onPrimary.copy(alpha = 0.65f) else t.inkSubtle)
            }
        }
    }
}

@Composable
private fun TargetList(list: List<Target>, activity: String, running: Boolean) {
    val t = LocalTokens.current
    val ctx = LocalContext.current
    Sheet(Modifier.fillMaxWidth(), padding = 0) {
        list.forEachIndexed { i, target ->
            if (i > 0) Box(Modifier.fillMaxWidth().height(1.dp).background(t.line2))
            Row(
                Modifier.fillMaxWidth().clickable(enabled = target.profileUrl != null) {
                    runCatching { ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(target.profileUrl))) }
                }.padding(horizontal = 16.dp, vertical = 12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Initial(target.username)
                Spacer(Modifier.width(12.dp))
                Column(Modifier.weight(1f)) {
                    Text("@${target.username}", style = Type.body, color = t.ink, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    val sub = target.error?.takeIf { target.status == "failed" || target.status == "skipped" }
                        ?: ago(target.sentAt ?: target.lastAttemptAt)?.let { "Last touched $it" }
                    if (sub != null) Text(sub, style = Type.small, color = t.inkSubtle, maxLines = 2, overflow = TextOverflow.Ellipsis)
                }
                Spacer(Modifier.width(8.dp))
                val (word, tone) = targetStatus(target.status, activity, running)
                StatusPill(word, tone)
                if (target.profileUrl != null) {
                    Spacer(Modifier.width(6.dp))
                    Icon(Icons.AutoMirrored.Outlined.OpenInNew, "Open profile", Modifier.size(14.dp), tint = t.inkSubtle)
                }
            }
        }
    }
}

@Composable
private fun Initial(name: String) {
    val t = LocalTokens.current
    Box(Modifier.size(34.dp).clip(CircleShape).background(t.tile), contentAlignment = Alignment.Center) {
        Text(name.firstOrNull()?.uppercase() ?: "?", style = Type.cardTitle, color = t.inkMuted)
    }
}

/** `processing` on a campaign that is not running is a job held for a
 *  cooldown, not work in progress — "Working" would be a claim. */
private fun targetStatus(status: String, activity: String, running: Boolean): Pair<String, Tone> = when (status) {
    "sent" -> when (activity) {
        "follow" -> "Followed"; "unfollow" -> "Unfollowed"; "comment" -> "Posted"; else -> "Sent"
    } to Tone.Good
    "failed" -> "Failed" to Tone.Bad
    "processing" -> if (running) "Working" to Tone.Warn else "Held" to Tone.Neutral
    "skipped" -> "Skipped" to Tone.Neutral
    "paused" -> "Waiting" to Tone.Neutral
    else -> "Queued" to Tone.Neutral
}

fun ago(iso: String?): String? {
    val then = iso?.let { runCatching { OffsetDateTime.parse(it) }.getOrNull() } ?: return null
    val d = Duration.between(then, OffsetDateTime.now())
    return when {
        d.toMinutes() < 1 -> "just now"
        d.toMinutes() < 60 -> "${d.toMinutes()}m ago"
        d.toHours() < 24 -> "${d.toHours()}h ago"
        else -> "${d.toDays()}d ago"
    }
}

private const val PAGE_SIZE = 25

@Composable
private fun Pager(page: Int, total: Int, busy: Boolean, onPrev: () -> Unit, onNext: () -> Unit) {
    val t = LocalTokens.current
    val pages = (total + PAGE_SIZE - 1) / PAGE_SIZE
    val from = page * PAGE_SIZE + 1
    val to = minOf(total, (page + 1) * PAGE_SIZE)
    Row(Modifier.fillMaxWidth().padding(top = 2.dp), verticalAlignment = Alignment.CenterVertically) {
        PagerButton("Previous", enabled = page > 0 && !busy, onClick = onPrev)
        Column(Modifier.weight(1f), horizontalAlignment = Alignment.CenterHorizontally) {
            Text("${groupThousands(from)}–${groupThousands(to)} of ${groupThousands(total)}",
                style = Type.small, color = t.ink)
            Text("Page ${page + 1} of $pages", style = Type.label, color = t.inkSubtle)
        }
        PagerButton("Next", enabled = page < pages - 1 && !busy, onClick = onNext)
    }
}

@Composable
private fun PagerButton(label: String, enabled: Boolean, onClick: () -> Unit) {
    val t = LocalTokens.current
    Box(
        Modifier.clip(RoundedCornerShape(12.dp)).background(t.card)
            .border(1.dp, t.border, RoundedCornerShape(12.dp))
            .clickable(enabled = enabled, onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 10.dp),
    ) { Text(label, style = Type.small, color = if (enabled) t.ink else t.inkSubtle.copy(alpha = 0.5f)) }
}
