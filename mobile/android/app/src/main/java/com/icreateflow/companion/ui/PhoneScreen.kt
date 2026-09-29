package com.icreateflow.companion.ui

import android.content.Intent
import android.provider.Settings
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import com.icreateflow.companion.CompanionApp
import com.icreateflow.companion.engine.FollowService
import com.icreateflow.companion.engine.FollowTest

/**
 * The phone as a worker: is it ready, and can it do the job.
 *
 * The follow service (the hands), the TikTok account it acts as, a one-off
 * test that reports to nobody, and — once linked to a sending account —
 * the switch that makes this phone take that account's campaign follows.
 */
@Composable
fun PhoneScreen(token: String, onSignedOut: () -> Unit) {
    val t = LocalTokens.current
    val ctx = LocalContext.current
    val session = (ctx.applicationContext as CompanionApp).session
    var enabled by remember { mutableStateOf(FollowService.isEnabled(ctx)) }
    val connected by FollowService.connected.collectAsState()
    var tiktok by remember { mutableStateOf(FollowService.installedTikTok(ctx)) }
    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) {
        enabled = FollowService.isEnabled(ctx)
        tiktok = FollowService.installedTikTok(ctx)
    }
    // Connected means switched on — Android binds nothing that isn't.
    val on = connected
    androidx.compose.runtime.LaunchedEffect(on, enabled) {
        android.util.Log.i(FollowService.TAG, "phone tab: connected=$on enabledInSettings=$enabled")
    }
    var me by remember { mutableStateOf(session.tiktokHandle.orEmpty()) }
    var target by remember { mutableStateOf("") }
    var mode by remember { mutableStateOf(0) }  // 0 follow, 1 message, 2 unfollow
    val testMessage = mode == 1
    var testText by remember { mutableStateOf("") }
    val prefill by FollowTest.prefill.collectAsState()
    androidx.compose.runtime.LaunchedEffect(prefill) {
        prefill?.let { target = it; FollowTest.prefill.value = null }
    }
    val run by FollowTest.state.collectAsState()

    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Column(Modifier.padding(horizontal = 4.dp)) {
            Text("Phone", style = Type.display, color = t.ink)
            Spacer(Modifier.height(4.dp))
            Text("This phone does follows and messages inside TikTok, where they stick.",
                style = Type.body, color = t.inkMuted)
        }

        Sheet(Modifier.fillMaxWidth()) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Phone service", style = Type.cardTitle, color = t.ink, modifier = Modifier.weight(1f))
                StatusPill(if (on) "On" else if (enabled) "Starting" else "Off",
                    if (on) Tone.Good else if (enabled) Tone.Warn else Tone.Neutral)
            }
            Spacer(Modifier.height(6.dp))
            Text(
                "Lets the app follow and message inside TikTok for you. It only reads, taps and types inside " +
                    "TikTok, and only when you or a campaign asks it to.",
                style = Type.small, color = t.inkMuted,
            )
            if (!on) {
                Spacer(Modifier.height(12.dp))
                Text(
                    "Settings → Accessibility → Installed apps → ICREATEFLOW follows → turn it on. " +
                        "If it's greyed out: App info → ⋮ → Allow restricted settings, then try again.",
                    style = Type.small, color = t.inkSubtle,
                )
                Spacer(Modifier.height(12.dp))
                Button(
                    onClick = { ctx.startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) },
                    modifier = Modifier.fillMaxWidth().height(48.dp), shape = RoundedCornerShape(50),
                    colors = ButtonDefaults.buttonColors(containerColor = t.primary, contentColor = t.onPrimary),
                ) { Text("Open Accessibility settings", style = Type.cardTitle) }
            }
        }

        Sheet(Modifier.fillMaxWidth()) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                PlatformTile("tiktok", 30)
                Spacer(Modifier.width(10.dp))
                Text("TikTok", style = Type.cardTitle, color = t.ink, modifier = Modifier.weight(1f))
                StatusPill(if (tiktok != null) "Installed" else "Not installed",
                    if (tiktok != null) Tone.Good else Tone.Bad)
            }
            Spacer(Modifier.height(12.dp))
            Text("Your TikTok handle on this phone", style = Type.small, color = t.ink)
            Spacer(Modifier.height(6.dp))
            Input(me, { me = it; session.tiktokHandle = it.trim().removePrefix("@") }, "@yourhandle")
            Spacer(Modifier.height(6.dp))
            Text("Checked before every tap, so the phone never acts as the wrong account.",
                style = Type.small, color = t.inkSubtle)
        }

        Sheet(Modifier.fillMaxWidth()) {
            Text("Test on one profile", style = Type.cardTitle, color = t.ink)
            Spacer(Modifier.height(4.dp))
            Text(
                when (mode) {
                    1 -> "The phone sends one message by itself, the way a campaign would, and checks it went out."
                    2 -> "The phone unfollows one person by itself, then reopens their profile to check it stuck."
                    else -> "The phone follows one person by itself, then reopens their profile to check it stuck."
                } + " Nothing is sent to icreateflow and no campaign is touched.",
                style = Type.small, color = t.inkMuted,
            )
            Spacer(Modifier.height(12.dp))
            Row(
                Modifier.clip(RoundedCornerShape(12.dp)).background(t.tile).padding(3.dp),
                horizontalArrangement = Arrangement.spacedBy(3.dp),
            ) {
                listOf(0 to "Follow", 1 to "Message", 2 to "Unfollow").forEach { (m, label) ->
                    val picked = mode == m
                    Box(
                        Modifier.clip(RoundedCornerShape(9.dp)).background(if (picked) t.card else t.tile)
                            .clickable(enabled = !run.running) { mode = m }
                            .padding(horizontal = 16.dp, vertical = 8.dp),
                    ) { Text(label, style = Type.small, color = if (picked) t.ink else t.inkMuted) }
                }
            }
            Spacer(Modifier.height(12.dp))
            Text(when (mode) { 1 -> "Profile to message"; 2 -> "Profile to unfollow"; else -> "Profile to follow" },
                style = Type.small, color = t.ink)
            Spacer(Modifier.height(6.dp))
            Input(target, { target = it }, when (mode) {
                1 -> "@an account you own"; 2 -> "@someone you follow"; else -> "@someone you don't follow yet" })
            if (testMessage) {
                Spacer(Modifier.height(12.dp))
                Text("Message", style = Type.small, color = t.ink)
                Spacer(Modifier.height(6.dp))
                Input(testText, { testText = it }, "What the phone should send")
            }
            Spacer(Modifier.height(12.dp))
            val jobsOn = com.icreateflow.companion.engine.FollowJobs.state.collectAsState().value.on
            val ready = on && tiktok != null && me.isNotBlank() && target.isNotBlank() && !run.running && !jobsOn &&
                (!testMessage || testText.isNotBlank())
            Button(
                onClick = {
                    when (mode) {
                        1 -> FollowTest.startMessage(ctx, me, target, testText)
                        2 -> FollowTest.startUnfollow(ctx, me, target)
                        else -> FollowTest.start(ctx, me, target)
                    }
                },
                enabled = ready,
                modifier = Modifier.fillMaxWidth().height(50.dp), shape = RoundedCornerShape(50),
                colors = ButtonDefaults.buttonColors(containerColor = t.primary, contentColor = t.onPrimary,
                    disabledContainerColor = t.tile, disabledContentColor = t.inkSubtle),
            ) {
                if (run.running) CircularProgressIndicator(Modifier.size(18.dp), color = t.inkSubtle, strokeWidth = 2.dp)
                else Text(when (mode) { 1 -> "Send the test message"; 2 -> "Unfollow them"; else -> "Run the test" },
                    style = Type.cardTitle)
            }
            if (!on) {
                Spacer(Modifier.height(8.dp))
                Text("Turn on the phone service first.", style = Type.small, color = t.inkSubtle)
            } else if (jobsOn) {
                Spacer(Modifier.height(8.dp))
                Text("Stop taking campaign jobs to run a test.", style = Type.small, color = t.inkSubtle)
            }
            if (run.steps.isNotEmpty()) {
                Spacer(Modifier.height(16.dp))
                run.steps.forEach { StepRow(it) }
            }
            run.summary?.let { summary ->
                Spacer(Modifier.height(12.dp))
                val good = run.outcome == FollowTest.Outcome.Followed
                Box(
                    Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp))
                        .background((if (good) t.good else t.warn).copy(alpha = 0.1f)).padding(12.dp),
                ) { Text(summary, style = Type.small, color = t.ink) }
            }
        }

        CampaignFollowsCard(token, me, on, onSignedOut)
    }
}

@Composable
private fun StepRow(step: FollowTest.Step) {
    val t = LocalTokens.current
    Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), verticalAlignment = Alignment.Top) {
        val (bg, icon) = when (step.ok) {
            true -> t.good to Icons.Rounded.Check
            false -> t.bad to Icons.Rounded.Close
            null -> t.inkSubtle to null
        }
        Box(Modifier.padding(top = 1.dp).size(18.dp).clip(CircleShape).background(bg.copy(alpha = 0.15f)),
            contentAlignment = Alignment.Center) {
            if (icon != null) Icon(icon, null, Modifier.size(12.dp), tint = bg)
            else Box(Modifier.size(5.dp).clip(CircleShape).background(bg))
        }
        Spacer(Modifier.width(10.dp))
        Text(step.text, style = Type.small, color = t.ink)
    }
}

@Composable
private fun Input(value: String, onChange: (String) -> Unit, placeholder: String) {
    val t = LocalTokens.current
    OutlinedTextField(
        value = value, onValueChange = onChange, singleLine = true,
        placeholder = { Text(placeholder, style = Type.body, color = t.inkSubtle) },
        textStyle = Type.body.copy(color = t.ink),
        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
        shape = RoundedCornerShape(50),
        colors = OutlinedTextFieldDefaults.colors(
            focusedBorderColor = t.ink, unfocusedBorderColor = t.border,
            focusedContainerColor = t.card, unfocusedContainerColor = t.card, cursorColor = t.ink,
        ),
        modifier = Modifier.fillMaxWidth(),
    )
}
