package com.icreateflow.companion.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.ChatBubbleOutline
import androidx.compose.material.icons.outlined.ModeComment
import androidx.compose.material.icons.outlined.PersonAddAlt
import androidx.compose.material.icons.outlined.PersonRemove
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp

/**
 * The website's kit, the parts the phone needs. Same shapes, same rules:
 * a card is a white raised sheet on the grey page, carried by the
 * lightness difference and a wide faint lift rather than a heavy border.
 */

val CardShape = RoundedCornerShape(16.dp)

@Composable
fun Sheet(modifier: Modifier = Modifier, padding: Int = 16, content: @Composable ColumnScope.() -> Unit) {
    val t = LocalTokens.current
    Column(
        modifier
            .shadow(10.dp, CardShape, ambientColor = Color(0x14101828), spotColor = Color(0x14101828))
            .clip(CardShape)
            .background(t.card)
            .border(1.dp, t.border, CardShape)
            .padding(padding.dp),
        content = content,
    )
}

/** The rounded tile a platform mark sits in — the site's `Avatar`. */
@Composable
fun PlatformTile(platform: String, size: Int = 34) {
    val t = LocalTokens.current
    Box(
        Modifier.size(size.dp).clip(RoundedCornerShape(10.dp)).background(t.tile)
            .border(1.dp, t.border, RoundedCornerShape(10.dp)),
        contentAlignment = Alignment.Center,
    ) { PlatformIcon(platform, t.ink, (size * 0.5f).dp) }
}

data class Task(val label: String, val icon: ImageVector)

fun taskOf(activity: String) = when (activity) {
    "follow" -> Task("Follow", Icons.Outlined.PersonAddAlt)
    "unfollow" -> Task("Unfollow", Icons.Outlined.PersonRemove)
    "comment" -> Task("Comment", Icons.Outlined.ModeComment)
    else -> Task("Message", Icons.Outlined.ChatBubbleOutline)
}

@Composable
fun TaskChip(activity: String) {
    val t = LocalTokens.current
    val task = taskOf(activity)
    Row(
        Modifier.clip(RoundedCornerShape(8.dp)).background(t.tile).padding(horizontal = 7.dp, vertical = 3.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Icon(task.icon, null, Modifier.size(12.dp), tint = t.inkMuted)
        Text(task.label, style = Type.small, color = t.inkMuted)
    }
}

/**
 * A status is a dot *and* a word, never colour alone — the site's rule.
 * Green is running, amber is waiting on the platform, red needs a person,
 * and everything else is ink.
 */
@Composable
fun StatusPill(word: String, tone: Tone) {
    val t = LocalTokens.current
    val c = when (tone) {
        Tone.Good -> t.good
        Tone.Warn -> t.warn
        Tone.Bad -> t.bad
        Tone.Neutral -> t.inkSubtle
    }
    Row(
        Modifier.clip(RoundedCornerShape(99.dp)).background(c.copy(alpha = 0.11f))
            .padding(horizontal = 9.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Box(Modifier.size(6.dp).clip(CircleShape).background(c))
        Text(word, style = Type.small, color = if (tone == Tone.Neutral) t.inkMuted else c)
    }
}

enum class Tone { Good, Warn, Bad, Neutral }

/** A thin track with the done share filled in the stepped-down brand lime. */
@Composable
fun Progress(fraction: Float, modifier: Modifier = Modifier) {
    val t = LocalTokens.current
    Box(modifier.fillMaxWidth().height(6.dp).clip(RoundedCornerShape(99.dp)).background(t.tile)) {
        Box(
            Modifier.fillMaxHeight().fillMaxWidth(fraction.coerceIn(0f, 1f))
                .clip(RoundedCornerShape(99.dp)).background(t.chart1),
        )
    }
}

fun groupThousands(n: Int): String = "%,d".format(n)
