package com.icreateflow.companion.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.scale
import androidx.compose.ui.graphics.vector.PathParser
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * Platform marks — the same SVG paths the website's `PlatformIcon` draws,
 * so a campaign looks the same on both. Instagram is the site's outline
 * glyph, drawn rather than parsed because it is three shapes, not a path.
 */
private val PATHS = mapOf(
    "tiktok" to "M21 8.6a6.6 6.6 0 0 1-4.6-1.9v7.9a6.2 6.2 0 1 1-5.4-6.1v2.9a3.3 3.3 0 1 0 2.5 3.2V2h2.9A6.6 6.6 0 0 0 21 6.7z",
    "x" to "M18.9 2H22l-7 8 8.2 12h-6.4l-5-7.3L5.9 22H2.8l7.5-8.6L2.5 2h6.6l4.5 6.6zm-1.1 18h1.7L7.3 3.8H5.5z",
    "youtube" to "M23 12s0-3.8-.5-5.6a2.9 2.9 0 0 0-2-2C18.7 4 12 4 12 4s-6.7 0-8.5.5a2.9 2.9 0 0 0-2 2C1 8.2 1 12 1 12s0 3.8.5 5.6a2.9 2.9 0 0 0 2 2C5.3 20 12 20 12 20s6.7 0 8.5-.5a2.9 2.9 0 0 0 2-2C23 15.8 23 12 23 12zM9.8 15.4V8.6l5.8 3.4z",
    "facebook" to "M22 12a10 10 0 1 0-11.6 9.9v-7h-2.5V12h2.5V9.8c0-2.5 1.5-3.9 3.8-3.9 1.1 0 2.2.2 2.2.2v2.5h-1.3c-1.2 0-1.6.8-1.6 1.6V12h2.8l-.4 2.9h-2.4v7A10 10 0 0 0 22 12z",
)

val PLATFORM_LABEL = mapOf(
    "tiktok" to "TikTok", "instagram" to "Instagram", "x" to "X",
    "youtube" to "YouTube", "facebook" to "Facebook",
)

@Composable
fun PlatformIcon(platform: String, tint: Color, size: Dp = 16.dp) {
    val d = PATHS[platform]
    val path = remember(d) { d?.let { PathParser().parsePathString(it).toPath() } }
    Canvas(Modifier.size(size)) {
        val k = this.size.width / 24f
        if (path != null) {
            scale(k, k, pivot = Offset.Zero) { drawPath(path, tint) }
        } else {
            // Instagram: rounded square, lens, flash dot.
            val w = 1.9f * k
            drawRoundRect(tint, topLeft = Offset(3 * k, 3 * k), size = Size(18 * k, 18 * k),
                cornerRadius = CornerRadius(5 * k), style = Stroke(w))
            drawCircle(tint, radius = 4 * k, center = Offset(12 * k, 12 * k), style = Stroke(w))
            drawCircle(tint, radius = 1.1f * k, center = Offset(17.3f * k, 6.7f * k))
        }
    }
}

