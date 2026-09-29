package com.icreateflow.companion.ui

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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.PhoneAndroid
import androidx.compose.material3.CircularProgressIndicator
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
import com.icreateflow.companion.data.SendingAccount
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * The sending accounts, and whether each one can send right now.
 *
 * The same list and the same one repair the website's Accounts page has:
 * a paused account can be resumed once whatever paused it is dealt with.
 * Adding accounts and signing them in stay on the website — that needs a
 * browser session the phone can't capture.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AccountsScreen(token: String, onSignedOut: () -> Unit) {
    val t = LocalTokens.current
    var accounts by remember { mutableStateOf<List<SendingAccount>?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var refreshing by remember { mutableStateOf(false) }
    var resuming by remember { mutableStateOf<Int?>(null) }
    val scope = rememberCoroutineScope()

    suspend fun load() {
        try { accounts = Api.accounts(token); error = null }
        catch (e: Api.ApiError) { if (e.status == 401) onSignedOut() else error = e.message }
    }
    LaunchedEffect(Unit) { while (true) { load(); delay(15_000) } }

    fun resume(a: SendingAccount) {
        if (resuming != null) return
        resuming = a.id
        scope.launch {
            try { Api.resumeAccount(token, a.id); load() }
            catch (e: Api.ApiError) { if (e.status == 401) onSignedOut() else error = e.message }
            finally { resuming = null }
        }
    }

    PullToRefreshBox(
        isRefreshing = refreshing,
        onRefresh = { scope.launch { refreshing = true; load(); refreshing = false } },
        modifier = Modifier.fillMaxSize(),
    ) {
        val list = accounts.orEmpty()
        val needs = list.count { stateOf(it).tone == Tone.Bad }
        LazyColumn(
            Modifier.fillMaxSize(),
            contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 12.dp, bottom = 24.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            item {
                Column(Modifier.padding(horizontal = 4.dp)) {
                    Text("Accounts", style = Type.display, color = t.ink)
                    Spacer(Modifier.height(4.dp))
                    Text(
                        when {
                            accounts == null -> "Loading…"
                            list.isEmpty() -> "No sending accounts yet."
                            needs > 0 -> "$needs of ${list.size} need attention."
                            else -> "All ${list.size} can send."
                        },
                        style = Type.body, color = t.inkMuted,
                    )
                }
            }
            error?.let { msg ->
                item {
                    Box(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(t.bad.copy(alpha = 0.08f)).padding(12.dp)) {
                        Text(msg, style = Type.small, color = t.ink)
                    }
                }
            }
            if (accounts != null && list.isEmpty()) {
                item {
                    Sheet(Modifier.fillMaxWidth()) {
                        Text("Add accounts on the website", style = Type.cardTitle, color = t.ink)
                        Spacer(Modifier.height(4.dp))
                        Text("Signing an account in needs a computer browser. Once added, it shows up here.",
                            style = Type.small, color = t.inkMuted)
                    }
                }
            }
            // Accounts that need a person first, then the rest by platform.
            val order = list.sortedWith(compareBy({ stateOf(it).tone != Tone.Bad }, { it.platform }, { it.name.lowercase() }))
            items(order, key = { it.id }) { a -> AccountCard(a, busy = resuming == a.id) { resume(a) } }
            if (list.isNotEmpty()) {
                item {
                    Text("Add or sign in accounts on the website.", style = Type.small, color = t.inkSubtle,
                        modifier = Modifier.padding(horizontal = 4.dp))
                }
            }
        }
    }
}

private data class AccountState(val word: String, val tone: Tone, val why: String? = null, val canResume: Boolean = false)

/** The website's `blockedReason`, in the same order: disabled, paused, signed out. */
private fun stateOf(a: SendingAccount): AccountState = when {
    !a.enabled -> AccountState("Disabled", Tone.Neutral, "Turned off — it won't be asked to send.")
    a.status == "paused" -> AccountState("Paused", Tone.Bad, a.pausedReason ?: "Paused after repeated failures", canResume = true)
    !a.hasSession && a.sessionReference == null -> AccountState("Signed out", Tone.Bad, "Sign it in again on the website.")
    a.status == "error" -> AccountState("Error", Tone.Bad, a.lastError)
    a.status == "active" -> AccountState("Sending", Tone.Good)
    a.purpose == "discovery" -> AccountState("Finds profiles", Tone.Neutral)
    else -> AccountState("Ready", Tone.Good)
}

@Composable
private fun AccountCard(a: SendingAccount, busy: Boolean, onResume: () -> Unit) {
    val t = LocalTokens.current
    val s = stateOf(a)
    Sheet(Modifier.fillMaxWidth()) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            PlatformTile(a.platform, 36)
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(a.name, style = Type.cardTitle, color = t.ink, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(
                    listOfNotNull(
                        PLATFORM_LABEL[a.platform] ?: a.platform,
                        "${groupThousands(a.processed)} done",
                        ago(a.lastActivityAt)?.let { "active $it" },
                    ).joinToString(" · "),
                    style = Type.small, color = t.inkSubtle, maxLines = 1, overflow = TextOverflow.Ellipsis,
                )
            }
            Spacer(Modifier.width(8.dp))
            StatusPill(s.word, s.tone)
        }
        if (a.platform == "tiktok" && !a.deviceHandle.isNullOrBlank()) {
            Spacer(Modifier.height(10.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Outlined.PhoneAndroid, null, Modifier.size(14.dp), tint = t.inkSubtle)
                Spacer(Modifier.width(6.dp))
                Text("Follows go through the phone as @${a.deviceHandle}", style = Type.small, color = t.inkMuted)
            }
        }
        s.why?.let { why ->
            Spacer(Modifier.height(10.dp))
            Box(
                Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp))
                    .background((if (s.tone == Tone.Bad) t.bad else t.tile).copy(alpha = if (s.tone == Tone.Bad) 0.08f else 1f))
                    .padding(12.dp),
            ) { Text(why, style = Type.small, color = t.inkMuted, maxLines = 4, overflow = TextOverflow.Ellipsis) }
        }
        if (s.canResume) {
            Spacer(Modifier.height(12.dp))
            val shape = RoundedCornerShape(50)
            Row(
                Modifier.fillMaxWidth().height(44.dp).clip(shape).background(t.primary)
                    .clickable(enabled = !busy, onClick = onResume),
                horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically,
            ) {
                if (busy) CircularProgressIndicator(Modifier.size(16.dp), color = t.onPrimary.copy(alpha = 0.6f), strokeWidth = 2.dp)
                else Text("Resume sending", style = Type.cardTitle, color = t.onPrimary)
            }
            Spacer(Modifier.height(6.dp))
            Text("Do this once the cause is dealt with — it pauses again if it isn't.",
                style = Type.small, color = t.inkSubtle)
        }
    }
}
