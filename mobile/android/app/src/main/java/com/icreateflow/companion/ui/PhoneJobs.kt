package com.icreateflow.companion.ui

import android.Manifest
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
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
import com.icreateflow.companion.CompanionApp
import com.icreateflow.companion.data.Api
import com.icreateflow.companion.data.PhoneAccount
import com.icreateflow.companion.engine.FollowJobs
import kotlinx.coroutines.launch

/**
 * The phone takes follows and messages from your campaigns.
 *
 * Link picks which TikTok sending account this phone works for; the server
 * then hands that account's campaign follows and messages to this phone
 * instead of doing them in a browser. "Take jobs" is the switch — while
 * it's on, the phone asks for work every few seconds and TikTok opens by
 * itself for each one.
 */
@Composable
fun CampaignFollowsCard(token: String, me: String, serviceOn: Boolean, onSignedOut: () -> Unit) {
    val t = LocalTokens.current
    val ctx = LocalContext.current
    val device = remember { (ctx.applicationContext as CompanionApp).session.deviceId }
    var accounts by remember { mutableStateOf<List<PhoneAccount>?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf<Int?>(null) }
    val jobs by FollowJobs.state.collectAsState()
    val scope = rememberCoroutineScope()

    suspend fun load() {
        try { accounts = Api.phoneAccounts(token, device); error = null }
        catch (e: Api.ApiError) { if (e.status == 401) onSignedOut() else error = e.message }
    }
    LaunchedEffect(token) { load() }

    fun act(id: Int, block: suspend () -> Unit) {
        if (busy != null) return
        busy = id
        scope.launch {
            try { block(); load() }
            catch (e: Api.ApiError) { if (e.status == 401) onSignedOut() else error = e.message }
            finally { busy = null }
        }
    }

    // Android 13+ asks before an app may show a notification. The service
    // runs either way; this only decides whether its status is visible.
    val askNotify = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
        FollowJobs.start(ctx)
    }
    fun startJobs() {
        if (Build.VERSION.SDK_INT >= 33) askNotify.launch(Manifest.permission.POST_NOTIFICATIONS)
        else FollowJobs.start(ctx)
    }

    val linked = accounts.orEmpty().filter { it.linked == "this" }

    Sheet(Modifier.fillMaxWidth()) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Campaign work", style = Type.cardTitle, color = t.ink, modifier = Modifier.weight(1f))
            StatusPill(if (jobs.on) "Working" else "Off", if (jobs.on) Tone.Good else Tone.Neutral)
        }
        Spacer(Modifier.height(6.dp))
        Text(
            "Link this phone to a TikTok sending account and its campaign follows, unfollows and messages come here " +
                "instead of the browser — the phone does them in TikTok and reports each one back.",
            style = Type.small, color = t.inkMuted,
        )

        error?.let {
            Spacer(Modifier.height(10.dp))
            Note(it, t.bad)
        }

        Spacer(Modifier.height(12.dp))
        when {
            accounts == null -> Text("Loading your TikTok accounts…", style = Type.small, color = t.inkSubtle)
            accounts!!.isEmpty() -> Text("You have no TikTok sending accounts. Add one on the website first.",
                style = Type.small, color = t.inkSubtle)
            else -> accounts!!.forEach { a ->
                AccountRow(a, me, busy == a.id,
                    onLink = { act(a.id) { Api.linkPhone(token, device, a.id, me) } },
                    onUnlink = {
                        if (jobs.on && linked.size == 1) FollowJobs.stop(ctx)
                        act(a.id) { Api.unlinkPhone(token, device, a.id) }
                    })
            }
        }

        if (linked.isNotEmpty()) {
            Spacer(Modifier.height(14.dp))
            val mismatch = linked.firstOrNull { !it.handle.equals(me.trim().removePrefix("@"), ignoreCase = true) }
            if (mismatch != null) {
                Note("@${mismatch.handle} is the handle the server will check for ${mismatch.name}; the box above " +
                    "says @${me.removePrefix("@")}. Link again to update it.", t.warn)
                Spacer(Modifier.height(10.dp))
            }
            val canStart = serviceOn || jobs.on
            PillButton(
                if (jobs.on) "Stop taking jobs" else "Take jobs",
                primary = !jobs.on, enabled = canStart,
            ) { if (jobs.on) FollowJobs.stop(ctx) else startJobs() }
            Spacer(Modifier.height(8.dp))
            if (!canStart) {
                Text("Turn on the phone service first.", style = Type.small, color = t.inkSubtle)
            } else if (jobs.on) {
                Text(jobs.line, style = Type.small, color = t.ink)
                Text(listOfNotNull("${jobs.done} done since you switched on", jobs.last?.let { "last: $it" })
                    .joinToString(" · "), style = Type.small, color = t.inkSubtle)
            } else {
                Text("While on, TikTok opens by itself for each follow or message and the screen stays on — the phone " +
                    "is busy. Keep it unlocked and charging.", style = Type.small, color = t.inkSubtle)
            }
        }
    }
}

@Composable
private fun AccountRow(a: PhoneAccount, me: String, busy: Boolean, onLink: () -> Unit, onUnlink: () -> Unit) {
    val t = LocalTokens.current
    Row(Modifier.fillMaxWidth().padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
        PlatformTile("tiktok", 32)
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f)) {
            Text(a.name, style = Type.body, color = t.ink, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(
                when (a.linked) {
                    "this" -> "Works through this phone as @${a.handle}"
                    "other" -> "Works through another phone" + (ago(a.seenAt)?.let { " · seen $it" } ?: "")
                    else -> "Works through the browser"
                },
                style = Type.small, color = if (a.linked == "this") t.good else t.inkSubtle,
                maxLines = 2, overflow = TextOverflow.Ellipsis,
            )
        }
        Spacer(Modifier.width(8.dp))
        val shape = RoundedCornerShape(50)
        val canLink = me.isNotBlank()
        Box(
            Modifier.clip(shape).background(if (a.linked == "this") t.card else t.primary)
                .border(1.dp, if (a.linked == "this") t.border else t.primary, shape)
                .clickable(enabled = !busy && (a.linked == "this" || canLink)) {
                    if (a.linked == "this") onUnlink() else onLink()
                }
                .padding(horizontal = 14.dp, vertical = 8.dp),
            contentAlignment = Alignment.Center,
        ) {
            if (busy) CircularProgressIndicator(Modifier.size(14.dp), strokeWidth = 2.dp,
                color = if (a.linked == "this") t.ink else t.onPrimary)
            else Text(
                when (a.linked) { "this" -> "Unlink"; "other" -> "Move here"; else -> "Link" },
                style = Type.small, color = if (a.linked == "this") t.ink else t.onPrimary,
            )
        }
    }
}

@Composable
private fun Note(text: String, tone: androidx.compose.ui.graphics.Color) {
    val t = LocalTokens.current
    Box(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(tone.copy(alpha = 0.08f)).padding(12.dp)) {
        Text(text, style = Type.small, color = t.ink)
    }
}

@Composable
private fun PillButton(label: String, primary: Boolean, enabled: Boolean, onClick: () -> Unit) {
    val t = LocalTokens.current
    val shape = RoundedCornerShape(50)
    Box(
        Modifier.fillMaxWidth().height(50.dp).clip(shape)
            .background(if (!enabled) t.tile else if (primary) t.primary else t.card)
            .border(1.dp, if (primary && enabled) t.primary else t.border, shape)
            .clickable(enabled = enabled, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Text(label, style = Type.cardTitle,
            color = if (!enabled) t.inkSubtle else if (primary) t.onPrimary else t.ink)
    }
}
