package com.icreateflow.companion.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.icreateflow.companion.CompanionApp
import com.icreateflow.companion.data.Api
import com.icreateflow.companion.data.Campaign
import com.icreateflow.companion.data.Lead
import com.icreateflow.companion.data.LeadAvailability
import com.icreateflow.companion.data.LeadSearchBody
import com.icreateflow.companion.data.LeadSearchState
import com.icreateflow.companion.engine.FollowService
import com.icreateflow.companion.engine.PhoneSearch
import androidx.compose.runtime.collectAsState
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlin.math.roundToInt

/**
 * Find profiles for a campaign — the website's lead finder, on the phone.
 *
 * Same three steps: describe who you want, watch it look, choose from what
 * it found. Nothing reaches the campaign until the last one. The search
 * itself runs on the server, in its discovery account's browser; the phone
 * only starts it, watches it and imports the result, so closing the app
 * costs the search nothing.
 *
 * Unlike the website's dialog, the search is remembered per campaign: a
 * search takes minutes, and a phone app is closed in that time far more
 * often than a browser tab. Reopening the finder goes back to it.
 */
@Composable
fun LeadFinderScreen(
    token: String, campaign: Campaign, onBack: () -> Unit, onImported: (String) -> Unit, onSignedOut: () -> Unit,
) {
    val t = LocalTokens.current
    BackHandler(onBack = onBack)
    val session = (LocalContext.current.applicationContext as CompanionApp).session
    val platform = campaign.platform
    val scope = rememberCoroutineScope()

    var availability by remember { mutableStateOf<LeadAvailability?>(null) }
    var resolving by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }

    var mode by remember { mutableStateOf("seeds") }
    // TikTok can also be read by this phone, in the TikTok app itself.
    val phoneOk = platform == "tiktok"
    var phoneVideos by remember { mutableStateOf("") }
    val phoneRun by PhoneSearch.state.collectAsState()
    val ctx = LocalContext.current
    var seeds by remember { mutableStateOf("") }
    var niche by remember { mutableStateOf("") }
    var location by remember { mutableStateOf("") }
    var interests by remember { mutableStateOf("") }
    var wanted by remember { mutableFloatStateOf(50f) }
    var commenters by remember { mutableStateOf(true) }
    var likers by remember { mutableStateOf(false) }
    var replies by remember { mutableStateOf(true) }
    var enrich by remember { mutableStateOf(false) }
    var accountId by remember { mutableStateOf<Int?>(null) }

    var searchId by remember { mutableStateOf<Int?>(null) }
    var progress by remember { mutableStateOf<SearchProgress?>(null) }
    var leads by remember { mutableStateOf<List<Lead>>(emptyList()) }
    var chosen by remember { mutableStateOf<Set<Int>>(emptySet()) }
    var pending by remember { mutableStateOf(0) }
    var campaigns by remember { mutableStateOf<List<Campaign>>(emptyList()) }
    var targets by remember { mutableStateOf(setOf(campaign.id)) }
    var busy by remember { mutableStateOf(false) }

    fun fail(e: Api.ApiError) { if (e.status == 401) onSignedOut() else error = e.message }

    /** Everything it found that isn't in a campaign yet — all ticked, as on the website. */
    suspend fun loadLeads(id: Int) {
        val found = Api.leads(token, id).filter { it.importedAt == null }
        leads = found
        chosen = found.map { it.id }.toSet()
        // Nothing left to choose from: the search is spent, start fresh next time.
        if (found.isEmpty()) session.setSearchFor(campaign.id, null)
    }

    suspend fun refreshPending() {
        pending = runCatching { Api.pendingLeads(token, platform).size }.getOrDefault(0)
    }

    LaunchedEffect(campaign.id) {
        try {
            val a = Api.leadAvailability(token, platform)
            availability = a
            // No server discovery here: the phone can still read TikTok itself.
            if (!a.available && phoneOk) mode = "phone"
            wanted = wanted.coerceAtMost(a.maxPerSearch.toFloat())
            accountId = (a.accounts.firstOrNull { !it.busy } ?: a.accounts.firstOrNull())?.id
            campaigns = runCatching { Api.campaigns(token).filter { it.platform == platform } }.getOrDefault(emptyList())
            session.searchFor(campaign.id)?.let { saved ->
                try {
                    val p = progressOf(Api.leadSearch(token, saved))
                    searchId = saved; progress = p
                    if (p.done) loadLeads(saved)
                } catch (e: Api.ApiError) {
                    if (e.status == 404) session.setSearchFor(campaign.id, null) else throw e
                }
            }
            refreshPending()
        } catch (e: Api.ApiError) { fail(e) }
        resolving = false
    }

    // A search takes minutes and outlives the request that started it.
    val running = searchId != null && progress?.done == false
    LaunchedEffect(searchId, running) {
        val id = searchId ?: return@LaunchedEffect
        while (running) {
            delay(2_000)
            try {
                val p = progressOf(Api.leadSearch(token, id))
                progress = p
                if (p.done) { loadLeads(id); refreshPending(); break }
            } catch (e: Api.ApiError) {
                if (e.status == 401) { onSignedOut(); break }
                // A dropped poll is not a failed search.
            }
        }
    }

    fun start() {
        if (busy) return
        busy = true; error = null
        scope.launch {
            try {
                if (mode == "phone") {
                    if (FollowService.instance == null) {
                        error = "Turn on the phone service first (Phone tab) — it is what reads TikTok."
                        return@launch
                    }
                    val run = Api.startPhoneSearch(token, campaign.id, phoneVideos.trim(), wanted.roundToInt(), replies,
                        session.deviceId)
                    if (!PhoneSearch.start(ctx, token, run.searchId, run.videos, run.wanted, replies)) {
                        Api.finishPhoneSearch(token, run.searchId, "cancelled", "Campaign work was on, so the phone didn't search.")
                        error = "Turn off campaign work on the Phone tab first — the phone does one thing at a time."
                        return@launch
                    }
                    session.setSearchFor(campaign.id, run.searchId)
                    leads = emptyList(); chosen = emptySet()
                    searchId = run.searchId
                    progress = SearchProgress(run.status, run.message, run.found, run.wanted, false)
                    return@launch
                }
                val run = Api.startLeadSearch(token, campaign.id, LeadSearchBody(
                    niche = if (mode == "niche") niche.trim() else "",
                    seedAccounts = if (mode == "seeds") seeds.trim().ifEmpty { null } else null,
                    location = location.trim().ifEmpty { null },
                    interests = interests.trim().ifEmpty { null },
                    wanted = wanted.roundToInt(),
                    platform = platform,
                    accountId = accountId,
                    commenters = commenters, likers = likers, replies = replies, enrich = enrich,
                ))
                session.setSearchFor(campaign.id, run.searchId)
                leads = emptyList(); chosen = emptySet()
                searchId = run.searchId
                progress = SearchProgress(run.status, run.message, run.found, run.wanted, run.done)
            } catch (e: Api.ApiError) { fail(e) } finally { busy = false }
        }
    }

    fun stop() {
        val id = searchId ?: return
        if (phoneRun.running && phoneRun.searchId == id) PhoneSearch.stop()
        scope.launch {
            try { Api.cancelLeadSearch(token, id) } catch (e: Api.ApiError) { fail(e) }
        }
    }

    fun showPending() {
        scope.launch {
            try {
                val found = Api.pendingLeads(token, platform)
                leads = found; chosen = found.map { it.id }.toSet()
            } catch (e: Api.ApiError) { fail(e) }
        }
    }

    fun importChosen() {
        if (busy || chosen.isEmpty() || targets.isEmpty()) return
        busy = true; error = null
        scope.launch {
            try {
                val out = Api.importLeads(token, campaign.id, leads.filter { it.id in chosen }.map { it.id }, targets.toList())
                session.setSearchFor(campaign.id, null)
                val split = out.campaigns.orEmpty()
                onImported(
                    if (split.size > 1) split.joinToString(", ") { "${groupThousands(it.ready)} to ${it.campaignName}" }
                    else "${groupThousands(out.ready)} added as targets",
                )
            } catch (e: Api.ApiError) { fail(e) } finally { busy = false }
        }
    }

    fun searchAgain() {
        session.setSearchFor(campaign.id, null)
        searchId = null; progress = null; leads = emptyList(); chosen = emptySet()
    }

    val a = availability
    val step = when {
        leads.isNotEmpty() -> 2
        running -> 1
        else -> 0
    }

    Column(Modifier.fillMaxSize()) {
        LazyColumn(
            Modifier.weight(1f).fillMaxWidth(),
            contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 4.dp, bottom = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            item {
                Row(
                    Modifier.clip(RoundedCornerShape(10.dp)).clickable(onClick = onBack).padding(vertical = 6.dp, horizontal = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(Icons.AutoMirrored.Outlined.ArrowBack, null, Modifier.size(18.dp), tint = t.inkMuted)
                    Spacer(Modifier.width(6.dp))
                    Text(campaign.name, style = Type.small, color = t.inkMuted, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            }
            item {
                Column(Modifier.padding(horizontal = 4.dp)) {
                    Text("Find profiles", style = Type.display, color = t.ink)
                    Spacer(Modifier.height(4.dp))
                    Text("A discovery account reads real posts and collects who engaged. Nothing reaches this " +
                        "campaign until you pick from what it finds.", style = Type.body, color = t.inkMuted)
                }
            }
            if (resolving) {
                item { Text("Loading…", style = Type.body, color = t.inkMuted, modifier = Modifier.padding(4.dp)) }
                return@LazyColumn
            }
            if ((a == null || !a.available) && !phoneOk) {
                item {
                    Sheet(Modifier.fillMaxWidth()) {
                        Text("Discovery isn't available", style = Type.cardTitle, color = t.ink)
                        Spacer(Modifier.height(4.dp))
                        Text(a?.unavailableReason ?: error ?: "Couldn't ask the server.", style = Type.small, color = t.inkMuted)
                    }
                }
                return@LazyColumn
            }
            item { Steps(step) }

            when (step) {
                0 -> {
                    // How the last search ended, when it ended with nothing to choose from.
                    progress?.takeIf { it.done && it.message.isNotBlank() }?.let { last ->
                        item { Note(last.message, if (last.status == "failed") t.bad else t.warn) }
                    }
                    if (mode != "phone" && a != null && a.accounts.isNotEmpty()) item {
                        Sheet(Modifier.fillMaxWidth()) {
                            Text("SEARCH FROM", style = Type.label, color = t.inkSubtle)
                            Spacer(Modifier.height(8.dp))
                            a.accounts.forEach { acc ->
                                ChoiceRow(
                                    on = acc.id == accountId, round = true, enabled = !acc.busy,
                                    title = acc.name,
                                    sub = if (acc.busy) "Running a search right now"
                                        else "${groupThousands(acc.usedToday)} opened in the last 24 hours",
                                ) { accountId = acc.id }
                            }
                            Spacer(Modifier.height(6.dp))
                            Text("A discovery account is separate from your senders, so looking around never " +
                                "spends a sending account's budget.", style = Type.small, color = t.inkSubtle)
                        }
                    }
                    item {
                        Sheet(Modifier.fillMaxWidth()) {
                            Text("WHERE TO LOOK", style = Type.label, color = t.inkSubtle)
                            Spacer(Modifier.height(8.dp))
                            Segment(buildList {
                                if (a?.available == true) { add("seeds" to "Posts"); add("niche" to "Description") }
                                if (phoneOk) add("phone" to "On this phone")
                            }, mode) { mode = it }
                            Spacer(Modifier.height(12.dp))
                            if (mode == "phone") {
                                Field(phoneVideos, { phoneVideos = it }, SEED_EXAMPLE.getValue("tiktok"), lines = 3)
                                Spacer(Modifier.height(6.dp))
                                Text("TikTok video links, one per line. This phone opens each video's comments in your " +
                                    "TikTok app and opens every commenter's profile for their @handle — about 20 a minute. " +
                                    "It only reads: nothing is followed, liked or messaged. People who keep their profile " +
                                    "view history on will see your account visited them.", style = Type.small, color = t.inkSubtle)
                                Spacer(Modifier.height(8.dp))
                                ChoiceRow(replies, title = "Open the reply threads",
                                    sub = "Where most of a busy video's people are") { replies = !replies }
                            } else if (mode == "seeds") {
                                Field(seeds, { seeds = it }, SEED_EXAMPLE[platform] ?: SEED_EXAMPLE.getValue("tiktok"), lines = 3)
                                Spacer(Modifier.height(6.dp))
                                Text(seedHint(seeds, replies), style = Type.small, color = t.inkSubtle)
                                Spacer(Modifier.height(8.dp))
                                ChoiceRow(commenters, title = "People who commented") { commenters = !commenters }
                                ChoiceRow(likers, title = "People who liked", sub = "One extra page load per post") { likers = !likers }
                                ChoiceRow(replies, title = "Open the reply threads",
                                    sub = "Where most of a busy video's people are") { replies = !replies }
                                ChoiceRow(enrich, title = "Open each profile for bio and follower count", sub = "Slower") { enrich = !enrich }
                            } else {
                                Text("Niche", style = Type.small, color = t.inkMuted)
                                Spacer(Modifier.height(4.dp))
                                Field(niche, { niche = it }, "streetwear resellers")
                                Spacer(Modifier.height(10.dp))
                                Text("Location", style = Type.small, color = t.inkMuted)
                                Spacer(Modifier.height(4.dp))
                                Field(location, { location = it }, "Lagos")
                                Spacer(Modifier.height(10.dp))
                                Text("Interests", style = Type.small, color = t.inkMuted)
                                Spacer(Modifier.height(4.dp))
                                Field(interests, { interests = it }, "sneakers, thrifting, hypebeast")
                            }
                        }
                    }
                    item {
                        Sheet(Modifier.fillMaxWidth()) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text("HOW MANY", style = Type.label, color = t.inkSubtle, modifier = Modifier.weight(1f))
                                Text(groupThousands(wanted.roundToInt()), style = Type.title, color = t.ink)
                            }
                            val cap = a?.maxPerSearch ?: 300
                            val max = cap.coerceAtLeast(20).toFloat()
                            Slider(
                                value = wanted, onValueChange = { wanted = (it / 10).roundToInt() * 10f },
                                valueRange = 10f..max,
                                colors = SliderDefaults.colors(
                                    thumbColor = t.ink, activeTrackColor = t.chart1, inactiveTrackColor = t.tile,
                                    activeTickColor = androidx.compose.ui.graphics.Color.Transparent,
                                    inactiveTickColor = androidx.compose.ui.graphics.Color.Transparent,
                                ),
                            )
                            Text("Up to ${groupThousands(cap)} per search. A search runs until the " +
                                "platform stops it.", style = Type.small, color = t.inkSubtle)
                        }
                    }
                    if (pending > 0) item {
                        Box(
                            Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(t.card)
                                .border(1.dp, t.border, RoundedCornerShape(12.dp))
                                .clickable { showPending() }.padding(14.dp),
                        ) {
                            Text("${groupThousands(pending)} already found but in no campaign — review them",
                                style = Type.small, color = t.inkMuted)
                        }
                    }
                }
                1 -> {
                    val p = progress!!
                    item {
                        Sheet(Modifier.fillMaxWidth()) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                CircularProgressIndicator(Modifier.size(22.dp), color = t.chart1, trackColor = t.tile, strokeWidth = 2.5.dp)
                                Spacer(Modifier.width(12.dp))
                                val mine = phoneRun.running && phoneRun.searchId == searchId
                                Text((if (mine) phoneRun.line else p.message).ifBlank { "Starting…" }, style = Type.cardTitle, color = t.ink)
                            }
                            Spacer(Modifier.height(16.dp))
                            Progress(if (p.wanted > 0) p.found.toFloat() / p.wanted else 0f)
                            Spacer(Modifier.height(14.dp))
                            Row(horizontalArrangement = Arrangement.spacedBy(24.dp)) {
                                Figure("FOUND", p.found)
                                Figure("WANTED", p.wanted)
                                Figure("LEFT", (p.wanted - p.found).coerceAtLeast(0))
                            }
                            Spacer(Modifier.height(14.dp))
                            Text(if (phoneRun.searchId == searchId) "This phone is reading TikTok — leave it on TikTok and " +
                                "unlocked until it finishes. It comes back here by itself when it's done."
                                else "This runs on the server and takes minutes. You can leave this screen or close " +
                                "the app — the search keeps going, and the results are waiting here when it finishes.",
                                style = Type.small, color = t.inkSubtle)
                        }
                    }
                }
                else -> {
                    item {
                        Row(Modifier.padding(horizontal = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                            Text("${groupThousands(leads.size)} found · ${groupThousands(chosen.size)} selected",
                                style = Type.small, color = t.inkMuted, modifier = Modifier.weight(1f))
                            val all = chosen.size == leads.size
                            Text(if (all) "Select none" else "Select all", style = Type.small, color = t.ink,
                                modifier = Modifier.clip(RoundedCornerShape(6.dp))
                                    .clickable { chosen = if (all) emptySet() else leads.map { it.id }.toSet() }
                                    .padding(6.dp))
                        }
                    }
                    items(leads, key = { it.id }) { lead ->
                        LeadRow(lead, lead.id in chosen) {
                            chosen = if (lead.id in chosen) chosen - lead.id else chosen + lead.id
                        }
                    }
                    if (campaigns.size > 1) item {
                        Sheet(Modifier.fillMaxWidth()) {
                            Text("SEND THESE TO", style = Type.label, color = t.inkSubtle)
                            Spacer(Modifier.height(6.dp))
                            campaigns.forEach { c ->
                                ChoiceRow(c.id in targets, title = c.name) {
                                    targets = if (c.id in targets) targets - c.id else targets + c.id
                                }
                            }
                            if (targets.size > 1) {
                                Spacer(Modifier.height(6.dp))
                                Text("Split evenly — about ${chosen.size / targets.size} each, dealt one at a time " +
                                    "rather than in blocks, so no campaign gets all the best leads.",
                                    style = Type.small, color = t.inkSubtle)
                            }
                        }
                    }
                }
            }
        }

        // The step's buttons stay in reach however long the list is.
        Column(Modifier.fillMaxWidth().background(t.page).padding(horizontal = 16.dp, vertical = 8.dp)) {
            error?.let { Note(it, t.bad); Spacer(Modifier.height(8.dp)) }
            if (!resolving && (a?.available == true || phoneOk)) when (step) {
                0 -> {
                    val serverBusy = mode != "phone" && a?.busy == true
                    if (serverBusy) {
                        Text(a?.busyReason ?: "No search can start right now.", style = Type.small, color = t.inkMuted)
                        Spacer(Modifier.height(8.dp))
                    }
                    val ready = when (mode) { "phone" -> phoneVideos.isNotBlank(); "seeds" -> seeds.isNotBlank(); else -> niche.isNotBlank() }
                    Pill(if (serverBusy) "Can't start yet" else if (busy) "Starting…" else "Find profiles",
                        primary = true, enabled = ready && !busy && !serverBusy) { start() }
                }
                1 -> Pill("Stop the search", primary = false, enabled = true) { stop() }
                else -> Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Box(Modifier.weight(1f)) { Pill("Search again", primary = false, enabled = !busy) { searchAgain() } }
                    Box(Modifier.weight(1.4f)) {
                        Pill(
                            when {
                                busy -> "Importing…"
                                targets.size > 1 -> "Import ${chosen.size} to ${targets.size}"
                                else -> "Import ${groupThousands(chosen.size)}"
                            },
                            primary = true, enabled = !busy && chosen.isNotEmpty() && targets.isNotEmpty(),
                        ) { importChosen() }
                    }
                }
            }
        }
    }
}

/** Where a search stands — the live run when the server process has it, otherwise its stored row. */
private data class SearchProgress(val status: String, val message: String, val found: Int, val wanted: Int, val done: Boolean)

private val FINISHED = setOf("done", "failed", "cancelled")

private fun progressOf(s: LeadSearchState): SearchProgress {
    s.run?.let { return SearchProgress(it.status, it.message, it.found, it.wanted, it.done) }
    // No live run here: another worker has it, or the process is gone. The
    // row is kept up to date as the search goes, so it is the truth either
    // way — and a row left "running" by a dead process is ended by Stop.
    val row = s.search
    return SearchProgress(row.status, row.message.orEmpty(), row.found ?: 0, row.wanted, row.status in FINISHED)
}

/** The same expression as the server's `_POST_URL`, so the hint describes what will happen. */
private val POST_LINK = Regex("""https?://\S*/(video|reel|p|status)/|tiktok\.com/t/""", RegexOption.IGNORE_CASE)

private val SEED_EXAMPLE = mapOf(
    "tiktok" to "https://www.tiktok.com/@creator/video/7412…",
    "instagram" to "https://www.instagram.com/p/abc123/",
    "x" to "https://x.com/someone/status/1834…",
)

private fun seedHint(seeds: String, replies: Boolean): String {
    val posts = seeds.split(Regex("""[\s,]+""")).count { POST_LINK.containsMatchIn(it) }
    return when {
        posts > 0 -> "Reading the comments on ${if (posts == 1) "that video" else "those $posts videos"}" +
            (if (replies) ", reply threads included. " else ", top-level comments only. ") +
            "Nothing is followed, liked or messaged; it only reads."
        seeds.isNotBlank() -> "Reading followers directly. Everyone here chose to follow those accounts, which is " +
            "a warmer list than a hashtag — it is also the most conspicuous thing this does, so keep the numbers modest."
        else -> "One post or profile per line. Their audience is who gets read."
    }
}

@Composable
private fun Steps(current: Int) {
    val t = LocalTokens.current
    Row(Modifier.padding(horizontal = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        listOf("Set up", "Searching", "Review").forEachIndexed { i, label ->
            if (i > 0) Box(Modifier.weight(1f).padding(horizontal = 8.dp).height(1.dp).background(t.border))
            val on = i <= current
            Box(
                Modifier.size(20.dp).clip(CircleShape).background(if (on) t.primary else t.tile),
                contentAlignment = Alignment.Center,
            ) { Text("${i + 1}", style = Type.label, color = if (on) t.onPrimary else t.inkSubtle) }
            Spacer(Modifier.width(6.dp))
            Text(label, style = Type.small, color = if (i == current) t.ink else t.inkSubtle)
        }
    }
}

@Composable
private fun Segment(items: List<Pair<String, String>>, current: String, onPick: (String) -> Unit) {
    val t = LocalTokens.current
    Row(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(t.tile).padding(3.dp),
        horizontalArrangement = Arrangement.spacedBy(3.dp),
    ) {
        items.forEach { (key, label) ->
            val on = key == current
            Box(
                Modifier.weight(1f).clip(RoundedCornerShape(9.dp)).background(if (on) t.card else t.tile)
                    .clickable { onPick(key) }.padding(vertical = 9.dp),
                contentAlignment = Alignment.Center,
            ) { Text(label, style = Type.small, color = if (on) t.ink else t.inkMuted) }
        }
    }
}

/** A tick box or, with `round`, a radio — the website's Checkbox and Radio. */
@Composable
private fun ChoiceRow(
    on: Boolean, round: Boolean = false, enabled: Boolean = true, title: String, sub: String? = null, onClick: () -> Unit,
) {
    val t = LocalTokens.current
    Row(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).clickable(enabled = enabled, onClick = onClick)
            .padding(vertical = 8.dp, horizontal = 2.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Tick(on, round, enabled)
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(title, style = Type.body, color = if (enabled) t.ink else t.inkSubtle, maxLines = 2, overflow = TextOverflow.Ellipsis)
            if (sub != null) Text(sub, style = Type.small, color = t.inkSubtle)
        }
    }
}

@Composable
private fun Tick(on: Boolean, round: Boolean = false, enabled: Boolean = true) {
    val t = LocalTokens.current
    val shape = if (round) CircleShape else RoundedCornerShape(6.dp)
    Box(
        Modifier.size(20.dp).clip(shape).background(if (on) t.primary else t.card)
            .border(1.5.dp, if (on) t.primary else if (enabled) t.border else t.line2, shape),
        contentAlignment = Alignment.Center,
    ) {
        if (on) {
            if (round) Box(Modifier.size(8.dp).clip(CircleShape).background(t.onPrimary))
            else Icon(Icons.Rounded.Check, null, Modifier.size(14.dp), tint = t.onPrimary)
        }
    }
}

@Composable
private fun LeadRow(lead: Lead, on: Boolean, onToggle: () -> Unit) {
    val t = LocalTokens.current
    Row(
        Modifier.fillMaxWidth().clip(CardShape).background(t.card).border(1.dp, t.border, CardShape)
            .clickable(onClick = onToggle).padding(horizontal = 14.dp, vertical = 11.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Tick(on)
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("@${lead.username}", style = Type.body, color = t.ink, maxLines = 1, overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f, fill = false))
                lead.score?.let {
                    Spacer(Modifier.width(8.dp))
                    Text("$it/100", style = Type.small, color = t.inkSubtle)
                }
            }
            val sub = listOfNotNull(
                lead.followers?.let { "${groupThousands(it)} followers" },
                (lead.bio ?: lead.reason ?: lead.source)?.takeIf { it.isNotBlank() },
            ).joinToString(" · ")
            if (sub.isNotEmpty()) Text(sub, style = Type.small, color = t.inkSubtle, maxLines = 2, overflow = TextOverflow.Ellipsis)
        }
    }
}

@Composable
private fun Figure(label: String, v: Int) {
    val t = LocalTokens.current
    Column {
        Text(groupThousands(v), style = Type.title, color = t.ink)
        Text(label, style = Type.label, color = t.inkSubtle)
    }
}

@Composable
private fun Field(value: String, onChange: (String) -> Unit, placeholder: String, lines: Int = 1) {
    val t = LocalTokens.current
    OutlinedTextField(
        value = value, onValueChange = onChange, singleLine = lines == 1, minLines = lines,
        placeholder = { Text(placeholder, style = Type.body, color = t.inkSubtle) },
        textStyle = Type.body.copy(color = t.ink),
        keyboardOptions = KeyboardOptions(imeAction = if (lines == 1) ImeAction.Done else ImeAction.Default),
        shape = RoundedCornerShape(14.dp),
        colors = OutlinedTextFieldDefaults.colors(
            focusedBorderColor = t.ink, unfocusedBorderColor = t.border,
            focusedContainerColor = t.card, unfocusedContainerColor = t.card, cursorColor = t.ink,
        ),
        modifier = Modifier.fillMaxWidth(),
    )
}

@Composable
private fun Note(text: String, tone: androidx.compose.ui.graphics.Color) {
    val t = LocalTokens.current
    Box(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(tone.copy(alpha = 0.08f)).padding(12.dp)) {
        Text(text, style = Type.small, color = t.ink)
    }
}

@Composable
private fun Pill(label: String, primary: Boolean, enabled: Boolean, onClick: () -> Unit) {
    val t = LocalTokens.current
    val shape = RoundedCornerShape(50)
    Box(
        Modifier.fillMaxWidth().height(50.dp).clip(shape)
            .background(if (!enabled) t.tile else if (primary) t.primary else t.card)
            .border(1.dp, if (primary && enabled) t.primary else t.border, shape)
            .clickable(enabled = enabled, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Text(label, style = Type.cardTitle, color = if (!enabled) t.inkSubtle else if (primary) t.onPrimary else t.ink)
    }
}
