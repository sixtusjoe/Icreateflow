package com.icreateflow.companion.ui

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
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.CloudOff
import androidx.compose.material.icons.outlined.Inbox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.icreateflow.companion.data.Api
import com.icreateflow.companion.data.Campaign
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.time.Duration
import java.time.OffsetDateTime
import kotlin.math.roundToInt

/**
 * Every campaign the signed-in user has, and what each one is doing.
 *
 * Read-only on purpose, for now: it answers "is it running, and if not, why
 * not" — the question the website's campaign page answers — from the same
 * `/api/outreach/campaigns` list the site uses. Nothing here is invented:
 * each figure is a field of that response, and every percentage says what
 * it is a percentage of.
 *
 * Refreshes itself every 15 seconds while open, and on pull-down.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DashboardScreen(token: String, firstName: String?, onOpen: (Int) -> Unit, onSignedOut: () -> Unit) {
    val t = LocalTokens.current
    var campaigns by remember { mutableStateOf<List<Campaign>?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var refreshing by remember { mutableStateOf(false) }
    var filter by remember { mutableStateOf(Filter.All) }
    val scope = rememberCoroutineScope()

    suspend fun load() {
        try {
            campaigns = Api.campaigns(token)
            error = null
        } catch (e: Api.ApiError) {
            if (e.status == 401) onSignedOut() else error = e.message
        }
    }

    LaunchedEffect(token) {
        while (true) {
            load()
            delay(15_000)
        }
    }

    val list = campaigns.orEmpty().sortedWith(
        compareBy<Campaign> { rank(it.status) }.thenByDescending { it.updatedAt ?: "" })
    val shown = list.filter { filter.matches(it.status) }

    PullToRefreshBox(
        isRefreshing = refreshing,
        onRefresh = { scope.launch { refreshing = true; load(); refreshing = false } },
        modifier = Modifier.fillMaxSize(),
    ) {
        LazyColumn(
            Modifier.fillMaxSize(),
            contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 12.dp, bottom = 24.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            item {
                Column(Modifier.padding(horizontal = 4.dp)) {
                    Text(greeting(firstName), style = Type.small, color = t.inkMuted)
                    Spacer(Modifier.height(2.dp))
                    Text("Campaigns", style = Type.display, color = t.ink)
                }
            }
            item { Summary(list) }
            item {
                Filters(filter, list) { filter = it }
            }
            when {
                campaigns == null && error == null -> item { Loading() }
                campaigns == null && error != null -> item { Problem(error!!) }
                shown.isEmpty() -> item { Empty(filter) }
                else -> {
                    if (error != null) item { StaleNote(error!!) }
                    items(shown, key = { it.id }) { CampaignCard(it) { onOpen(it.id) } }
                }
            }
        }
    }
}

private fun greeting(name: String?): String {
    val h = java.time.LocalTime.now().hour
    val part = when { h < 12 -> "Good morning"; h < 17 -> "Good afternoon"; else -> "Good evening" }
    return if (name.isNullOrBlank()) part else "$part, $name"
}

private fun rank(status: String) = when (status) {
    "running" -> 0; "paused" -> 1; "draft" -> 2; else -> 3
}

enum class Filter(val label: String) {
    All("All"), Running("Running"), Paused("Paused"), Draft("Drafts"), Finished("Finished");

    fun matches(status: String) = when (this) {
        All -> true
        Running -> status == "running"
        Paused -> status == "paused"
        Draft -> status == "draft"
        Finished -> status == "completed" || status == "stopped"
    }
}

@Composable
private fun Summary(list: List<Campaign>) {
    val t = LocalTokens.current
    val running = list.count { it.status == "running" }
    val paused = list.count { it.status == "paused" }
    val finished = list.count { it.status == "completed" || it.status == "stopped" }
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Stat("RUNNING", running, t.good, Modifier.weight(1f))
        Stat("PAUSED", paused, t.warn, Modifier.weight(1f))
        Stat("FINISHED", finished, t.inkSubtle, Modifier.weight(1f))
    }
}

@Composable
private fun Stat(label: String, value: Int, dot: androidx.compose.ui.graphics.Color, modifier: Modifier) {
    val t = LocalTokens.current
    Sheet(modifier, padding = 14) {
        Text("$value", style = Type.figure, color = t.ink)
        Spacer(Modifier.height(4.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(6.dp).clip(RoundedCornerShape(99.dp)).background(dot))
            Spacer(Modifier.width(6.dp))
            Text(label, style = Type.label, color = t.inkSubtle)
        }
    }
}

@Composable
private fun Filters(current: Filter, list: List<Campaign>, onPick: (Filter) -> Unit) {
    val t = LocalTokens.current
    Row(
        Modifier.horizontalScroll(rememberScrollState()).clip(RoundedCornerShape(12.dp))
            .background(t.card).border(1.dp, t.border, RoundedCornerShape(12.dp)).padding(3.dp),
        horizontalArrangement = Arrangement.spacedBy(3.dp),
    ) {
        Filter.entries.forEach { f ->
            val on = f == current
            val n = list.count { f.matches(it.status) }
            Row(
                Modifier.clip(RoundedCornerShape(9.dp)).background(if (on) t.primary else t.card)
                    .clickable { onPick(f) }.padding(horizontal = 12.dp, vertical = 7.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(f.label, style = Type.small, color = if (on) t.onPrimary else t.inkMuted)
                Spacer(Modifier.width(5.dp))
                Text("$n", style = Type.label, color = if (on) t.onPrimary.copy(alpha = 0.65f) else t.inkSubtle)
            }
        }
    }
}

/** What state a campaign is in, as a word and a tone — and why, when paused. */
fun campaignStatus(c: Campaign): Pair<String, Tone> = when (c.status) {
    "running" -> "Running" to Tone.Good
    "paused" -> when {
        c.messageRefused -> "Message refused" to Tone.Bad
        c.pausedUntil != null -> ("Paused · " + resumesIn(c.pausedUntil)) to Tone.Warn
        else -> "Paused" to Tone.Neutral
    }
    "completed" -> "Completed" to Tone.Neutral
    "stopped" -> "Stopped" to Tone.Neutral
    else -> "Draft" to Tone.Neutral
}

fun resumesIn(iso: String): String {
    val until = runCatching { OffsetDateTime.parse(iso) }.getOrNull() ?: return "paused"
    val left = Duration.between(OffsetDateTime.now(), until)
    if (left.isNegative) return "resuming"
    val h = left.toHours(); val m = left.toMinutes() % 60
    return if (h > 0) "back in ${h}h ${m}m" else "back in ${m}m"
}

/** The unit a campaign's targets are counted in. */
private fun unitOf(activity: String) = if (activity == "comment") "comments" else "profiles"

@Composable
private fun CampaignCard(c: Campaign, onClick: () -> Unit) {
    val t = LocalTokens.current
    val (word, tone) = campaignStatus(c)
    val total = c.totalTargets
    val fraction = if (total > 0) c.processed.toFloat() / total else 0f
    Sheet(Modifier.fillMaxWidth().clip(CardShape).clickable(onClick = onClick)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            PlatformTile(c.platform)
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(c.name, style = Type.cardTitle, color = t.ink, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Spacer(Modifier.height(4.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    TaskChip(c.activity)
                    Spacer(Modifier.width(6.dp))
                    Text(PLATFORM_LABEL[c.platform] ?: c.platform, style = Type.small, color = t.inkSubtle)
                }
            }
        }
        Spacer(Modifier.height(12.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            StatusPill(word, tone)
        }
        Spacer(Modifier.height(14.dp))
        Progress(fraction)
        Spacer(Modifier.height(8.dp))
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text(
                "${groupThousands(c.processed)} of ${groupThousands(total)} ${unitOf(c.activity)} worked",
                style = Type.small, color = t.inkMuted, modifier = Modifier.weight(1f),
            )
            Text(if (total > 0) "${(fraction * 100).roundToInt()}%" else "—", style = Type.small, color = t.ink)
        }
        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            Figure("SUCCEEDED", c.successful)
            Figure("FAILED", c.failed)
            Figure("LEFT", (total - c.processed).coerceAtLeast(0))
        }
        val reason = c.pausedReason
        if (c.status == "paused" && !reason.isNullOrBlank()) {
            Spacer(Modifier.height(12.dp))
            Box(
                Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp))
                    .background((if (tone == Tone.Bad) t.bad else t.warn).copy(alpha = 0.08f))
                    .padding(horizontal = 12.dp, vertical = 10.dp),
            ) {
                Text(reason, style = Type.small, color = t.inkMuted, maxLines = 3, overflow = TextOverflow.Ellipsis)
            }
        }
    }
}

@Composable
private fun Figure(label: String, value: Int) {
    val t = LocalTokens.current
    Column {
        Text(groupThousands(value), style = Type.cardTitle, color = t.ink)
        Text(label, style = Type.label, color = t.inkSubtle)
    }
}

@Composable
private fun Loading() {
    val t = LocalTokens.current
    Box(Modifier.fillMaxWidth().padding(vertical = 48.dp), contentAlignment = Alignment.Center) {
        Text("Loading your campaigns…", style = Type.body, color = t.inkMuted)
    }
}

@Composable
private fun Problem(message: String) {
    val t = LocalTokens.current
    Sheet(Modifier.fillMaxWidth()) {
        Icon(Icons.Outlined.CloudOff, null, tint = t.inkMuted)
        Spacer(Modifier.height(8.dp))
        Text("Couldn't load your campaigns", style = Type.cardTitle, color = t.ink)
        Spacer(Modifier.height(4.dp))
        Text("$message. Pull down to try again.", style = Type.small, color = t.inkMuted)
    }
}

@Composable
private fun StaleNote(message: String) {
    val t = LocalTokens.current
    Text("Showing the last list we got — $message.", style = Type.small, color = t.warn,
        modifier = Modifier.padding(horizontal = 4.dp))
}

@Composable
private fun Empty(filter: Filter) {
    val t = LocalTokens.current
    Sheet(Modifier.fillMaxWidth()) {
        Icon(Icons.Outlined.Inbox, null, tint = t.inkMuted)
        Spacer(Modifier.height(8.dp))
        Text(
            if (filter == Filter.All) "No campaigns yet" else "Nothing ${filter.label.lowercase()} right now",
            style = Type.cardTitle, color = t.ink,
        )
        Spacer(Modifier.height(4.dp))
        Text("Campaigns are created on icreateflow.com and show up here.", style = Type.small, color = t.inkMuted)
    }
}
