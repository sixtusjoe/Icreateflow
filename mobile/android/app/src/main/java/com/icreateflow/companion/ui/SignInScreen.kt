package com.icreateflow.companion.ui

import androidx.compose.foundation.Image
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
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Visibility
import androidx.compose.material.icons.outlined.VisibilityOff
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.icreateflow.companion.BuildConfig
import com.icreateflow.companion.R
import com.icreateflow.companion.data.Api
import com.icreateflow.companion.data.Login
import kotlinx.coroutines.launch

/**
 * Sign in, sign up, and reset a password — the three things the website's
 * auth offers, and nothing it does not.
 *
 * The layout follows the reference the user chose (a centred mark and
 * wordmark, bold labels over pill fields, one full-width pill button, the
 * way to the other screen underneath), in this product's own ink rather
 * than the reference's green: status green is reserved for status here.
 *
 * No "Continue with Google / Facebook / Apple": the backend has no social
 * sign-in, and a button with nothing behind it is the thing the design's
 * honesty rule forbids. They can be added once the backend supports them.
 *
 * Sign-up lands in `pending` exactly as on the website — an admin approves
 * the account before it can sign in — so the screen says so rather than
 * pretending the user is in.
 */
@Composable
fun SignInScreen(onSignedIn: (Login) -> Unit) {
    var mode by remember { mutableStateOf(Mode.SignIn) }
    var email by remember { mutableStateOf("") }
    when (mode) {
        Mode.SignIn -> SignIn(email, { email = it }, onSignedIn, { mode = Mode.SignUp }, { mode = Mode.Forgot })
        Mode.SignUp -> SignUp(email, { email = it }) { mode = Mode.SignIn }
        Mode.Forgot -> Forgot(email, { email = it }) { mode = Mode.SignIn }
    }
}

private enum class Mode { SignIn, SignUp, Forgot }

private val EMAIL = Regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]{2,}$")

@Composable
private fun AuthPage(content: @Composable () -> Unit) {
    val t = LocalTokens.current
    Box(Modifier.fillMaxSize().background(t.card).systemBarsPadding().imePadding()) {
        Column(
            Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Spacer(Modifier.height(56.dp))
            Image(painterResource(R.drawable.brand_logo), contentDescription = null,
                modifier = Modifier.size(56.dp).clip(RoundedCornerShape(15.dp)))
            Spacer(Modifier.height(14.dp))
            Text("ICREATEFLOW", style = Type.display.copy(fontSize = 30.sp, fontWeight = FontWeight.Bold,
                letterSpacing = (-0.4).sp), color = t.ink)
            Spacer(Modifier.height(36.dp))
            content()
            Spacer(Modifier.height(28.dp))
            val app = androidx.compose.ui.platform.LocalContext.current.applicationContext as com.icreateflow.companion.CompanionApp
            var current by remember { mutableStateOf(Api.base) }
            var picking by remember { mutableStateOf(false) }
            ServerLine(current) { picking = true }
            if (picking) ServerDialog(current, onDismiss = { picking = false }) { picked ->
                app.session.server = picked
                Api.base = picked
                current = picked
                picking = false
            }
            Spacer(Modifier.height(24.dp))
        }
    }
}

@Composable
private fun SignIn(
    email: String, onEmail: (String) -> Unit, onSignedIn: (Login) -> Unit,
    toSignUp: () -> Unit, toForgot: () -> Unit,
) {
    val t = LocalTokens.current
    var password by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    fun submit() {
        if (busy) return
        if (!EMAIL.matches(email.trim()) || password.isEmpty()) { error = "Enter your email and password"; return }
        busy = true; error = null
        scope.launch {
            try { onSignedIn(Api.login(email, password)) }
            catch (e: Api.ApiError) { error = e.message }
            finally { busy = false }
        }
    }
    AuthPage {
        Field("Email", email, { onEmail(it); error = null }, "you@example.com", KeyboardType.Email,
            ImeAction.Next, valid = EMAIL.matches(email.trim()))
        Spacer(Modifier.height(18.dp))
        Field("Password", password, { password = it; error = null }, "Enter your password",
            KeyboardType.Password, ImeAction.Done, secret = true, onDone = ::submit)
        Row(Modifier.fillMaxWidth().padding(top = 10.dp), horizontalArrangement = Arrangement.End) {
            Text("Forgot password?", style = Type.small, color = t.inkMuted,
                modifier = Modifier.clip(RoundedCornerShape(6.dp)).clickable(onClick = toForgot).padding(4.dp))
        }
        ErrorLine(error)
        Spacer(Modifier.height(18.dp))
        PillButton("Log in", busy, ::submit)
        Spacer(Modifier.height(22.dp))
        SwitchLine("Don't have an account?", "Sign up", toSignUp)
    }
}

@Composable
private fun SignUp(email: String, onEmail: (String) -> Unit, toSignIn: () -> Unit) {
    val t = LocalTokens.current
    var name by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var done by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    fun submit() {
        if (busy) return
        when {
            name.isBlank() -> { error = "Enter your name"; return }
            !EMAIL.matches(email.trim()) -> { error = "Enter a valid email"; return }
            password.length < 6 -> { error = "Password must be at least 6 characters"; return }
        }
        busy = true; error = null
        scope.launch {
            try { done = Api.register(name, email, password) }
            catch (e: Api.ApiError) { error = e.message }
            finally { busy = false }
        }
    }
    AuthPage {
        if (done != null) {
            Notice("Account created", done!!)
            Spacer(Modifier.height(22.dp))
            PillButton("Back to log in", false, toSignIn)
            return@AuthPage
        }
        Field("Name", name, { name = it; error = null }, "Your name", KeyboardType.Text, ImeAction.Next,
            valid = name.trim().length >= 2)
        Spacer(Modifier.height(18.dp))
        Field("Email", email, { onEmail(it); error = null }, "you@example.com", KeyboardType.Email,
            ImeAction.Next, valid = EMAIL.matches(email.trim()))
        Spacer(Modifier.height(18.dp))
        Field("Password", password, { password = it; error = null }, "At least 6 characters",
            KeyboardType.Password, ImeAction.Done, secret = true, onDone = ::submit,
            valid = password.length >= 6)
        ErrorLine(error)
        Spacer(Modifier.height(24.dp))
        PillButton("Create account", busy, ::submit)
        Spacer(Modifier.height(12.dp))
        Text("New accounts are approved by an admin before they can log in.",
            style = Type.small, color = t.inkSubtle, textAlign = TextAlign.Center)
        Spacer(Modifier.height(18.dp))
        SwitchLine("Already have an account?", "Log in", toSignIn)
    }
}

@Composable
private fun Forgot(email: String, onEmail: (String) -> Unit, toSignIn: () -> Unit) {
    var sent by remember { mutableStateOf(false) }
    var code by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var done by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    fun send() {
        if (busy) return
        if (!EMAIL.matches(email.trim())) { error = "Enter a valid email"; return }
        busy = true; error = null
        scope.launch {
            try { Api.forgotPassword(email); sent = true }
            catch (e: Api.ApiError) { error = e.message }
            finally { busy = false }
        }
    }
    fun reset() {
        if (busy) return
        if (code.isBlank() || password.length < 6) { error = "Enter the code and a new password of 6+ characters"; return }
        busy = true; error = null
        scope.launch {
            try { Api.resetPassword(email, code, password); done = true }
            catch (e: Api.ApiError) { error = e.message }
            finally { busy = false }
        }
    }
    AuthPage {
        when {
            done -> {
                Notice("Password changed", "Log in with your new password.")
                Spacer(Modifier.height(22.dp))
                PillButton("Back to log in", false, toSignIn)
            }
            !sent -> {
                Notice("Reset your password", "We'll email you a code if this address has an account.")
                Spacer(Modifier.height(22.dp))
                Field("Email", email, { onEmail(it); error = null }, "you@example.com", KeyboardType.Email,
                    ImeAction.Done, valid = EMAIL.matches(email.trim()), onDone = ::send)
                ErrorLine(error)
                Spacer(Modifier.height(24.dp))
                PillButton("Send code", busy, ::send)
                Spacer(Modifier.height(22.dp))
                SwitchLine("Remembered it?", "Log in", toSignIn)
            }
            else -> {
                Notice("Check your email", "Enter the code we sent to ${email.trim()} and choose a new password.")
                Spacer(Modifier.height(22.dp))
                Field("Code", code, { code = it; error = null }, "6-digit code", KeyboardType.Number, ImeAction.Next)
                Spacer(Modifier.height(18.dp))
                Field("New password", password, { password = it; error = null }, "At least 6 characters",
                    KeyboardType.Password, ImeAction.Done, secret = true, onDone = ::reset,
                    valid = password.length >= 6)
                ErrorLine(error)
                Spacer(Modifier.height(24.dp))
                PillButton("Change password", busy, ::reset)
                Spacer(Modifier.height(22.dp))
                SwitchLine("Didn't get it?", "Send again") { sent = false }
            }
        }
    }
}

@Composable
private fun Notice(title: String, body: String) {
    val t = LocalTokens.current
    Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
        Text(title, style = Type.title, color = t.ink)
        Spacer(Modifier.height(6.dp))
        Text(body, style = Type.body, color = t.inkMuted, textAlign = TextAlign.Center)
    }
}

@Composable
private fun ErrorLine(error: String?) {
    if (error == null) return
    val t = LocalTokens.current
    Text(error, style = Type.small, color = t.bad, modifier = Modifier.fillMaxWidth().padding(top = 10.dp))
}

@Composable
private fun SwitchLine(lead: String, action: String, onClick: () -> Unit) {
    val t = LocalTokens.current
    Text(
        buildAnnotatedString {
            withStyle(SpanStyle(color = t.inkMuted)) { append("$lead ") }
            withStyle(SpanStyle(color = t.ink, fontWeight = FontWeight.SemiBold)) { append(action) }
        },
        style = Type.body,
        modifier = Modifier.clip(RoundedCornerShape(8.dp)).clickable(onClick = onClick).padding(6.dp),
    )
}

@Composable
private fun PillButton(label: String, busy: Boolean, onClick: () -> Unit) {
    val t = LocalTokens.current
    Button(
        onClick = onClick, enabled = !busy,
        modifier = Modifier.fillMaxWidth().height(56.dp),
        shape = RoundedCornerShape(50),
        colors = ButtonDefaults.buttonColors(containerColor = t.primary, contentColor = t.onPrimary,
            disabledContainerColor = t.primary.copy(alpha = 0.55f), disabledContentColor = t.onPrimary),
    ) {
        if (busy) CircularProgressIndicator(Modifier.size(20.dp), color = t.onPrimary, strokeWidth = 2.dp)
        else Text(label, style = Type.cardTitle.copy(fontSize = 16.sp))
    }
}

@Composable
private fun Field(
    label: String, value: String, onChange: (String) -> Unit, placeholder: String,
    keyboard: KeyboardType, ime: ImeAction, secret: Boolean = false, valid: Boolean = false,
    onDone: () -> Unit = {},
) {
    val t = LocalTokens.current
    var shown by remember { mutableStateOf(false) }
    Column(Modifier.fillMaxWidth()) {
        Text(label, style = Type.cardTitle.copy(fontSize = 16.sp), color = t.ink)
        Spacer(Modifier.height(8.dp))
        OutlinedTextField(
            value = value, onValueChange = onChange, singleLine = true,
            placeholder = { Text(placeholder, style = Type.body, color = t.inkSubtle) },
            textStyle = Type.body.copy(color = t.ink, fontSize = 15.sp),
            visualTransformation = if (secret && !shown) PasswordVisualTransformation() else VisualTransformation.None,
            keyboardOptions = KeyboardOptions(keyboardType = keyboard, imeAction = ime),
            keyboardActions = KeyboardActions(onDone = { onDone() }),
            trailingIcon = {
                when {
                    secret -> Icon(
                        if (shown) Icons.Outlined.VisibilityOff else Icons.Outlined.Visibility,
                        contentDescription = if (shown) "Hide password" else "Show password",
                        tint = t.inkSubtle,
                        modifier = Modifier.clip(CircleShape).clickable { shown = !shown }.padding(6.dp),
                    )
                    valid && value.isNotEmpty() -> Box(
                        Modifier.size(22.dp).clip(CircleShape).background(t.good),
                        contentAlignment = Alignment.Center,
                    ) { Icon(Icons.Rounded.Check, contentDescription = "Looks right", tint = t.card, modifier = Modifier.size(14.dp)) }
                }
            },
            shape = RoundedCornerShape(50),
            colors = OutlinedTextFieldDefaults.colors(
                focusedBorderColor = t.ink, unfocusedBorderColor = t.border,
                focusedContainerColor = t.card, unfocusedContainerColor = t.card, cursorColor = t.ink,
            ),
            modifier = Modifier.fillMaxWidth().height(58.dp),
        )
    }
}
