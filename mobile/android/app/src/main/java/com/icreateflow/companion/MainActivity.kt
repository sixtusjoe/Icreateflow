package com.icreateflow.companion

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.AccountCircle
import androidx.compose.material.icons.outlined.Campaign
import androidx.compose.material.icons.outlined.Group
import androidx.compose.material.icons.outlined.PhoneAndroid
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
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
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.dp
import com.icreateflow.companion.data.Api
import kotlinx.coroutines.launch
import com.icreateflow.companion.ui.CompanionTheme
import com.icreateflow.companion.ui.DashboardScreen
import com.icreateflow.companion.ui.LocalTokens
import com.icreateflow.companion.ui.Sheet
import com.icreateflow.companion.ui.SignInScreen
import com.icreateflow.companion.ui.Type

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        takePrefill(intent)
        val session = (application as CompanionApp).session
        setContent {
            CompanionTheme {
                var token by remember { mutableStateOf(session.token) }
                val signOut = { session.clear(); token = null }
                if (token == null) {
                    SignInScreen { login ->
                        session.token = login.token
                        session.name = login.user.name
                        session.email = login.user.email
                        token = login.token
                    }
                } else {
                    Home(token!!, session.name, session.email, signOut)
                }
            }
        }
    }

    override fun onNewIntent(intent: android.content.Intent) {
        super.onNewIntent(intent)
        takePrefill(intent)
    }

    /** Review builds only: a follow-test target sent from the Mac. */
    private fun takePrefill(intent: android.content.Intent?) {
        if (!BuildConfig.DEBUG) return
        // `--es server https://…` points the app at another address of the
        // same server (a new tunnel), keeping the sign-in.
        intent?.getStringExtra("server")?.let { url ->
            com.icreateflow.companion.ui.normaliseServer(url)?.let {
                (application as CompanionApp).session.server = it
                Api.base = it
            }
        }
        // `--es message_to someone --es message_text "…"` sends one message
        // with the job's own steps and logs each one (adb logcat -s IcfFollow).
        intent?.getStringExtra("message_to")?.let { to ->
            val me = (application as CompanionApp).session.tiktokHandle
            val body = intent.getStringExtra("message_text").orEmpty()
            if (me.isNullOrBlank() || body.isBlank()) {
                android.util.Log.i(com.icreateflow.companion.engine.FollowService.TAG, "message test refused: no handle or text")
            } else {
                val app = applicationContext
                kotlinx.coroutines.CoroutineScope(kotlinx.coroutines.Dispatchers.Main).launch {
                    val out = com.icreateflow.companion.engine.Messenger.send(app, me, to, body) { line, ok ->
                        android.util.Log.i(com.icreateflow.companion.engine.FollowService.TAG,
                            "msg ${when (ok) { true -> "ok"; false -> "FAIL"; null -> ".." }} $line")
                    }
                    android.util.Log.i(com.icreateflow.companion.engine.FollowService.TAG,
                        "msg result ${out.status} ${out.error ?: ""}")
                }
            }
            return
        }
        val target = intent?.getStringExtra("follow_target") ?: return
        com.icreateflow.companion.engine.FollowTest.prefill.value = target
        openPhoneTab.value = true
        // `--ez follow_run true` presses Run too. A screen read from the Mac
        // pauses the follow service, so the button can't be found by reading
        // the screen and then pressed with it still switched on.
        if (intent.getBooleanExtra("follow_run", false)) {
            val me = (application as CompanionApp).session.tiktokHandle
            if (me.isNullOrBlank()) android.util.Log.i(com.icreateflow.companion.engine.FollowService.TAG, "run refused: no handle")
            // `--es follow_mode unfollow` runs the unfollow test instead —
            // it opens the profile the same way and presses nothing on
            // someone this account doesn't follow.
            else if (intent.getStringExtra("follow_mode") == "unfollow")
                com.icreateflow.companion.engine.FollowTest.startUnfollow(this, me, target)
            else com.icreateflow.companion.engine.FollowTest.start(this, me, target)
        }
    }
}

/** Set when a prefill arrives, so Home switches to the Phone tab. */
private val openPhoneTab = kotlinx.coroutines.flow.MutableStateFlow(false)

private enum class Tab(val label: String, val icon: ImageVector) {
    Campaigns("Campaigns", Icons.Outlined.Campaign),
    Accounts("Accounts", Icons.Outlined.Group),
    Phone("Phone", Icons.Outlined.PhoneAndroid),
    Account("Account", Icons.Outlined.AccountCircle),
}

@Composable
private fun Home(token: String, name: String?, email: String?, onSignOut: () -> Unit) {
    val t = LocalTokens.current
    var tab by remember { mutableStateOf(Tab.Campaigns) }
    var open by remember { mutableStateOf<Int?>(null) }
    val toPhone by openPhoneTab.collectAsState()
    androidx.compose.runtime.LaunchedEffect(toPhone) {
        if (toPhone) { tab = Tab.Phone; openPhoneTab.value = false }
    }
    Column(Modifier.fillMaxSize().background(t.page)) {
        TopBar()
        Box(Modifier.weight(1f)) {
            when (tab) {
                Tab.Campaigns -> if (open == null) {
                    DashboardScreen(token, name?.substringBefore(' '), { open = it }, onSignOut)
                } else {
                    com.icreateflow.companion.ui.CampaignScreen(token, open!!, { open = null }, onSignOut)
                }
                Tab.Accounts -> com.icreateflow.companion.ui.AccountsScreen(token, onSignOut)
                Tab.Phone -> com.icreateflow.companion.ui.PhoneScreen(token, onSignOut)
                Tab.Account -> AccountScreen(name, email, onSignOut)
            }
        }
        BottomBar(tab) { tab = it; open = null }
    }
}

@Composable
private fun TopBar() {
    val t = LocalTokens.current
    Row(
        Modifier.fillMaxWidth().statusBarsPadding().padding(horizontal = 20.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Image(painterResource(R.drawable.brand_logo), contentDescription = null,
            modifier = Modifier.size(28.dp).clip(RoundedCornerShape(8.dp)))
        Spacer(Modifier.width(10.dp))
        Text("ICREATEFLOW", style = Type.label.copy(letterSpacing = androidx.compose.ui.unit.TextUnit(1.4f, androidx.compose.ui.unit.TextUnitType.Sp)), color = t.ink)
    }
}

/**
 * Floating, like the site's glass rail: a raised pill over the page. Only
 * the current tab carries its word — four labels don't fit a phone's width,
 * and the website's task tabs work the same way.
 */
@Composable
private fun BottomBar(current: Tab, onPick: (Tab) -> Unit) {
    val t = LocalTokens.current
    Box(Modifier.fillMaxWidth().navigationBarsPadding().padding(horizontal = 16.dp, vertical = 10.dp)) {
        Row(
            Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).background(t.card)
                .border(1.dp, t.border, RoundedCornerShape(18.dp)).padding(5.dp),
            horizontalArrangement = Arrangement.spacedBy(5.dp),
        ) {
            Tab.entries.forEach { tab ->
                val on = tab == current
                Row(
                    Modifier.weight(if (on) 1.8f else 1f).clip(RoundedCornerShape(13.dp))
                        .background(if (on) t.primary else t.card)
                        .clickable { onPick(tab) }.padding(vertical = 11.dp),
                    horizontalArrangement = Arrangement.Center,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(tab.icon, tab.label, Modifier.size(18.dp), tint = if (on) t.onPrimary else t.inkMuted)
                    if (on) {
                        Spacer(Modifier.width(7.dp))
                        Text(tab.label, style = Type.small, color = t.onPrimary, maxLines = 1)
                    }
                }
            }
        }
    }
}

@Composable
private fun AccountScreen(name: String?, email: String?, onSignOut: () -> Unit) {
    val t = LocalTokens.current
    Column(Modifier.fillMaxSize().padding(horizontal = 16.dp, vertical = 12.dp)) {
        Text("Account", style = Type.display, color = t.ink, modifier = Modifier.padding(horizontal = 4.dp))
        Spacer(Modifier.height(16.dp))
        Sheet(Modifier.fillMaxWidth()) {
            Text("SIGNED IN AS", style = Type.label, color = t.inkSubtle)
            Spacer(Modifier.height(6.dp))
            Text(name ?: "—", style = Type.cardTitle, color = t.ink)
            Text(email ?: "", style = Type.small, color = t.inkMuted)
            Spacer(Modifier.height(14.dp))
            Text("SERVER", style = Type.label, color = t.inkSubtle)
            Spacer(Modifier.height(2.dp))
            // A sign-in belongs to one server, so changing it signs out.
            val app = androidx.compose.ui.platform.LocalContext.current.applicationContext as CompanionApp
            var picking by remember { mutableStateOf(false) }
            com.icreateflow.companion.ui.ServerLine(Api.base) { picking = true }
            if (picking) com.icreateflow.companion.ui.ServerDialog(Api.base, onDismiss = { picking = false }) { picked ->
                picking = false
                if (picked != Api.base) {
                    com.icreateflow.companion.engine.FollowJobs.stop(app)
                    app.session.server = picked
                    Api.base = picked
                    onSignOut()
                }
            }
            Spacer(Modifier.height(18.dp))
            Button(
                onClick = onSignOut, modifier = Modifier.fillMaxWidth().height(46.dp),
                shape = RoundedCornerShape(12.dp),
                colors = ButtonDefaults.buttonColors(containerColor = t.tile, contentColor = t.ink),
            ) { Text("Sign out", style = Type.cardTitle) }
        }
        Spacer(Modifier.height(12.dp))
        Text("Version ${BuildConfig.VERSION_NAME}", style = Type.small, color = t.inkSubtle,
            modifier = Modifier.padding(horizontal = 4.dp))
    }
}
