package com.icreateflow.companion.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import com.icreateflow.companion.R

/**
 * The website's design tokens, restated for the phone.
 *
 * Every value here is copied from `frontend/src/app/globals.css`, not chosen
 * again: the app is the same product, and a second palette would drift. The
 * same rules carry over — the page sits darker than the cards so each card
 * reads as a raised sheet; ink comes in three steps; status colours are for
 * status only and always travel with a word.
 *
 * Dark is its own palette (the site's `.dark` block), not a computed flip.
 */
@Immutable
data class Tokens(
    val page: Color,
    val card: Color,
    val ink: Color,
    val inkMuted: Color,
    val inkSubtle: Color,
    val border: Color,
    val line2: Color,
    val tile: Color,
    val primary: Color,
    val onPrimary: Color,
    val good: Color,
    val bad: Color,
    val warn: Color,
    val chart1: Color,
    val lime: Color,
)

val LightTokens = Tokens(
    page = Color(0xFFEEF0F4),
    card = Color(0xFFFFFFFF),
    ink = Color(0xFF0B0D12),
    inkMuted = Color(0xFF5B6272),
    inkSubtle = Color(0xFF8B92A3),
    border = Color(0xFFE8EAF0),
    line2 = Color(0xFFF0F2F6),
    tile = Color(0xFFF2F4F8),
    primary = Color(0xFF0B0D12),
    onPrimary = Color(0xFFFFFFFF),
    good = Color(0xFF12A150),
    bad = Color(0xFFE5484D),
    warn = Color(0xFFB25E09),
    chart1 = Color(0xFF8A8A00),
    lime = Color(0xFFD7D700),
)

val DarkTokens = Tokens(
    page = Color(0xFF0C0E13),
    card = Color(0xFF15181F),
    ink = Color(0xFFF2F4F8),
    inkMuted = Color(0xFFA3ABBD),
    inkSubtle = Color(0xFF727A8C),
    border = Color(0xFF242934),
    line2 = Color(0xFF1E232C),
    tile = Color(0xFF1B1F28),
    primary = Color(0xFFF2F4F8),
    onPrimary = Color(0xFF0C0E13),
    good = Color(0xFF3DD68C),
    bad = Color(0xFFFF6369),
    warn = Color(0xFFF2A25C),
    chart1 = Color(0xFF9A9B00),
    lime = Color(0xFFD7D700),
)

val LocalTokens = staticCompositionLocalOf { LightTokens }

val Geist = FontFamily(
    Font(R.font.geist_400, FontWeight.Normal),
    Font(R.font.geist_500, FontWeight.Medium),
    Font(R.font.geist_600, FontWeight.SemiBold),
    Font(R.font.geist_700, FontWeight.Bold),
)
val GeistMono = FontFamily(Font(R.font.geist_mono_500, FontWeight.Medium))

/** The type steps the site uses, by role rather than by size. */
object Type {
    val display = TextStyle(fontFamily = Geist, fontWeight = FontWeight.SemiBold, fontSize = 26.sp, letterSpacing = (-0.6).sp, lineHeight = 30.sp)
    val title = TextStyle(fontFamily = Geist, fontWeight = FontWeight.SemiBold, fontSize = 17.sp, letterSpacing = (-0.2).sp)
    val cardTitle = TextStyle(fontFamily = Geist, fontWeight = FontWeight.SemiBold, fontSize = 15.sp, letterSpacing = (-0.1).sp)
    val body = TextStyle(fontFamily = Geist, fontWeight = FontWeight.Normal, fontSize = 14.sp, lineHeight = 20.sp)
    val small = TextStyle(fontFamily = Geist, fontWeight = FontWeight.Medium, fontSize = 12.5.sp, lineHeight = 17.sp)
    /** The uppercase label under a figure — the third ink step. */
    val label = TextStyle(fontFamily = Geist, fontWeight = FontWeight.Bold, fontSize = 10.5.sp, letterSpacing = 0.9.sp)
    val figure = TextStyle(fontFamily = Geist, fontWeight = FontWeight.SemiBold, fontSize = 24.sp, letterSpacing = (-0.5).sp)
    val mono = TextStyle(fontFamily = GeistMono, fontWeight = FontWeight.Medium, fontSize = 12.sp)
}

@Composable
fun CompanionTheme(content: @Composable () -> Unit) {
    val dark = isSystemInDarkTheme()
    val t = if (dark) DarkTokens else LightTokens
    val scheme = if (dark) {
        darkColorScheme(primary = t.primary, onPrimary = t.onPrimary, background = t.page,
            surface = t.card, onSurface = t.ink, onBackground = t.ink, error = t.bad)
    } else {
        lightColorScheme(primary = t.primary, onPrimary = t.onPrimary, background = t.page,
            surface = t.card, onSurface = t.ink, onBackground = t.ink, error = t.bad)
    }
    androidx.compose.runtime.CompositionLocalProvider(LocalTokens provides t) {
        MaterialTheme(colorScheme = scheme, content = content)
    }
}
