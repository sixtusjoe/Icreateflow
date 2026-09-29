package com.icreateflow.companion.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.icreateflow.companion.BuildConfig
import com.icreateflow.companion.data.Api
import kotlinx.coroutines.launch

/** The live site. */
const val LIVE_SERVER = "https://icreateflow.com"

/**
 * "192.168.1.212:8000" → "http://192.168.1.212:8000"; a bare name gets https.
 * A computer on your own Wi-Fi is plain http; everything else must be https.
 */
fun normaliseServer(raw: String): String? {
    val s = raw.trim().trimEnd('/')
    if (s.isEmpty()) return null
    if (s.startsWith("http://") || s.startsWith("https://")) return s
    val host = s.substringBefore(':').substringBefore('/')
    val local = host == "localhost" || host.matches(Regex("""\d{1,3}(\.\d{1,3}){3}"""))
    return (if (local) "http://" else "https://") + s
}

/** Where the app is talking to, in a few words. */
fun serverLabel(base: String): String = when {
    base == LIVE_SERVER -> "icreateflow.com"
    base.contains("127.0.0.1") || base.contains("localhost") -> "Your computer, over USB"
    else -> base.removePrefix("http://").removePrefix("https://")
}

/** A tappable "Server · x · Change" line. */
@Composable
fun ServerLine(current: String, onChange: () -> Unit) {
    val t = LocalTokens.current
    Text(
        "Server · ${serverLabel(current)} · Change",
        style = Type.small, color = t.inkSubtle,
        modifier = Modifier.clip(RoundedCornerShape(6.dp)).clickable(onClick = onChange).padding(6.dp),
    )
}

/**
 * Pick the server: the live site, or ICREATEFLOW running on a computer on
 * the same Wi-Fi, by its address. The address is checked before it's kept,
 * so a typo can't leave the app pointing nowhere.
 */
@Composable
fun ServerDialog(current: String, onDismiss: () -> Unit, onPicked: (String) -> Unit) {
    val t = LocalTokens.current
    var address by remember {
        mutableStateOf(if (current == LIVE_SERVER) "" else current.removePrefix("http://").removePrefix("https://"))
    }
    var checking by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()

    fun tryServer(base: String) {
        checking = true; error = null
        scope.launch {
            if (Api.reachable(base)) onPicked(base)
            else error = "Nothing answered at ${serverLabel(base)}. Check the address, that ICREATEFLOW is " +
                "running there, and that the phone is on the same Wi-Fi."
            checking = false
        }
    }

    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = t.card,
        title = { Text("Server", style = Type.title, color = t.ink) },
        text = {
            Column {
                Text("Use the live site, or ICREATEFLOW running on a computer on this Wi-Fi.",
                    style = Type.body, color = t.inkMuted)
                Spacer(Modifier.height(14.dp))
                OutlinedTextField(
                    value = address, onValueChange = { address = it; error = null }, singleLine = true,
                    placeholder = { Text("192.168.1.20:8000", style = Type.body, color = t.inkSubtle) },
                    label = { Text("Computer's address", style = Type.small) },
                    textStyle = Type.body.copy(color = t.ink),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                    shape = RoundedCornerShape(14.dp),
                    colors = OutlinedTextFieldDefaults.colors(focusedBorderColor = t.ink, unfocusedBorderColor = t.border),
                    modifier = Modifier.fillMaxWidth(),
                )
                if (!BuildConfig.DEBUG) {
                    Spacer(Modifier.height(6.dp))
                    Text("This build only talks to https addresses.", style = Type.small, color = t.inkSubtle)
                }
                error?.let {
                    Spacer(Modifier.height(10.dp))
                    Text(it, style = Type.small, color = t.bad)
                }
                if (checking) {
                    Spacer(Modifier.height(10.dp))
                    Text("Checking…", style = Type.small, color = t.inkMuted)
                }
            }
        },
        confirmButton = {
            TextButton(enabled = !checking && address.isNotBlank(), onClick = {
                normaliseServer(address)?.let(::tryServer)
            }) { Text("Use this computer", style = Type.cardTitle, color = t.ink) }
        },
        dismissButton = {
            TextButton(enabled = !checking, onClick = { tryServer(LIVE_SERVER) }) {
                Text("Use the live site", style = Type.cardTitle, color = t.inkMuted)
            }
        },
    )
}
