#!/usr/bin/env node
/**
 * Standalone Remotion render script.
 * Called by the backend to render a video from the AudioVideo composition.
 *
 * Usage:
 *   node render.mjs --props '{"themeId":"minimal",...}' --output /path/to/out.mp4 --duration 30
 *
 * Strategy:
 * 1. Use renderFrames() to capture PNG screenshots (no compositor binary needed)
 * 2. Encode PNGs to H264 MP4 with system FFmpeg
 *
 * This bypasses @remotion/compositor-linux-x64-gnu/remotion which requires
 * GLIBC_2.35 (not available on AlmaLinux 9 / RHEL 9 which ships GLIBC 2.34).
 */
import { bundle } from "@remotion/bundler";
import { renderFrames, selectComposition } from "@remotion/renderer";
import path from "path";
import fs from "fs";
import os from "os";
import { spawnSync } from "child_process";
import { fileURLToPath } from "url";
import { parseArgs } from "util";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Cache the bundle across invocations to skip webpack (~2-3 min overhead)
const BUNDLE_CACHE_FILE = path.join(__dirname, ".bundle-cache.json");

function getCachedBundle() {
  try {
    const { location, mtime } = JSON.parse(fs.readFileSync(BUNDLE_CACHE_FILE, "utf8"));
    if (fs.existsSync(path.join(location, "index.html"))) {
      const entryMtime = fs.statSync(path.resolve(__dirname, "index.ts")).mtimeMs;
      if (entryMtime <= mtime) return location;
    }
  } catch {}
  return null;
}

function saveBundleCache(location) {
  try {
    const mtime = fs.statSync(path.resolve(__dirname, "index.ts")).mtimeMs;
    fs.writeFileSync(BUNDLE_CACHE_FILE, JSON.stringify({ location, mtime }));
  } catch {}
}

const { values } = parseArgs({
  options: {
    props: { type: "string" },
    output: { type: "string" },
    duration: { type: "string", default: "30" },
    fps: { type: "string", default: "30" },
  },
});

const inputProps = JSON.parse(values.props || "{}");
const outputLocation = values.output || "/tmp/remotion-output.mp4";
const durationSec = parseFloat(values.duration || "30");
const fps = parseInt(values.fps || "30", 10);
const durationInFrames = Math.ceil(durationSec * fps);

// Find system Chromium
function findChromium() {
  const candidates = [
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/google-chrome",
  ];
  for (const c of candidates) {
    if (fs.existsSync(c)) return c;
  }
  return null;
}

// Find system FFmpeg
function findFfmpeg() {
  for (const p of ["/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg", "ffmpeg"]) {
    try { if (p.startsWith("/") && !fs.existsSync(p)) continue; return p; } catch {}
  }
  return "ffmpeg"; // rely on PATH
}

async function main() {
  const chromiumPath = findChromium();
  const ffmpegPath = findFfmpeg();
  console.log(`[render] Chromium: ${chromiumPath || "auto-download"}`);
  console.log(`[render] FFmpeg: ${ffmpegPath}`);

  // ── Bundle ────────────────────────────────────────────────────────────────
  let bundleLocation = getCachedBundle();
  if (bundleLocation) {
    console.log(`[render] Using cached bundle: ${bundleLocation}`);
  } else {
    console.log("[render] Bundling composition...");
    bundleLocation = await bundle({
      entryPoint: path.resolve(__dirname, "index.ts"),
      webpackOverride: (config) => config,
    });
    saveBundleCache(bundleLocation);
    console.log("[render] Bundle cached for future renders.");
  }

  // ── Select composition ────────────────────────────────────────────────────
  console.log("[render] Selecting composition...");
  const composition = await selectComposition({
    serveUrl: bundleLocation,
    id: "AudioVideo",
    inputProps,
    ...(chromiumPath ? { browserExecutable: chromiumPath } : {}),
  });
  composition.durationInFrames = durationInFrames;
  composition.fps = fps;

  // Ensure output directory exists
  const outDir = path.dirname(outputLocation);
  if (!fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true });

  // ── Render frames to JPEGs (with resumption on double-crash) ─────────────
  const framesDir = path.join(os.tmpdir(), `remotion-frames-${Date.now()}`);
  fs.mkdirSync(framesDir, { recursive: true });

  console.log(`[render] Rendering ${durationInFrames} frames (${durationSec}s @ ${fps}fps) → ${outputLocation}`);

  // renderFrames() has MAX_RETRIES_PER_FRAME=1 hardcoded.  A frame that crashes
  // twice in a row causes a fatal error.  We wrap it in a resume loop: on failure,
  // detect the last successfully written frame, then restart from the next one.
  let totalRendered = 0;
  let startFrame = 0;
  const MAX_RESUME_ATTEMPTS = durationInFrames; // at most one resume per frame
  let resumeAttempts = 0;

  while (startFrame < durationInFrames && resumeAttempts < MAX_RESUME_ATTEMPTS) {
    const frameRange = [startFrame, durationInFrames - 1];
    try {
      await renderFrames({
        composition,
        serveUrl: bundleLocation,
        outputDir: framesDir,
        inputProps,
        imageFormat: "jpeg",
        jpegQuality: 90,
        frameRange,
        ...(chromiumPath ? { browserExecutable: chromiumPath } : {}),
        chromiumOptions: { gl: "swangle", disableWebSecurity: true },
        concurrency: 1,
        timeoutInMilliseconds: 60000,
        onFrameUpdate: (rendered) => {
          // rendered = count rendered THIS invocation; add startFrame for global index
          const globalRendered = startFrame + rendered;
          const pct = Math.round((globalRendered / durationInFrames) * 100);
          process.stdout.write(`[render] Progress: ${pct}% (rendered ${globalRendered}, encoded 0)\n`);
        },
      });
      // Success — all remaining frames rendered
      break;
    } catch (err) {
      const msg = err?.message || String(err);
      if (!msg.includes("Target closed") && !msg.includes("Session closed")) throw err;

      // Browser double-crashed: find the last successfully written frame file,
      // then resume from the next frame.
      const files = fs.readdirSync(framesDir)
        .filter(f => f.startsWith("element-") && f.endsWith(".jpeg"))
        .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));

      if (files.length === 0) throw err; // No frames rendered at all — give up

      // Remotion names frame files by ABSOLUTE frame index (element-143.jpeg = frame 143).
      // So just parse the last file's numeric suffix to get the last rendered frame.
      const lastFileName = files[files.length - 1]; // e.g. "element-0143.jpeg"
      const lastAbsoluteFrame = parseInt(lastFileName.replace(/^element-/, "").replace(/\.[^.]+$/, ""), 10);
      const nextFrame = lastAbsoluteFrame + 1;

      if (nextFrame >= durationInFrames) break; // All done

      console.log(`[render] Browser double-crash. Last frame rendered: ${lastAbsoluteFrame}. Resuming from frame ${nextFrame} (attempt ${resumeAttempts + 1})...`);
      startFrame = nextFrame;
      resumeAttempts++;

      // Brief pause to let Chromium fully clean up before restarting
      await new Promise(r => setTimeout(r, 1000));
    }
  }

  if (startFrame >= durationInFrames && resumeAttempts >= MAX_RESUME_ATTEMPTS) {
    throw new Error("Too many resume attempts — render could not complete");
  }

  console.log(`[render] All frames rendered. Encoding with FFmpeg...`);

  // ── Encode with system FFmpeg ─────────────────────────────────────────────
  // Build a concat file listing frames in sorted order.
  // (Remotion v4 uses dynamic zero-padding: 3 digits for <1000 frames,
  // 4 digits for <10000 frames, etc. — simpler to just sort the dir.)
  const frameFiles = fs.readdirSync(framesDir)
    .filter(f => f.endsWith(".jpeg") || f.endsWith(".png"))
    .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));

  if (frameFiles.length === 0) throw new Error("No frame files found after rendering");

  const concatFile = path.join(framesDir, "_concat.txt");
  fs.writeFileSync(concatFile, frameFiles.map(f => `file '${path.join(framesDir, f)}'`).join("\n"));

  const result = spawnSync(ffmpegPath, [
    "-y",
    "-r", String(fps),
    "-f", "concat",
    "-safe", "0",
    "-i", concatFile,
    "-c:v", "libx264",
    "-preset", "ultrafast",
    "-crf", "23",
    "-pix_fmt", "yuv420p",
    outputLocation,
  ], { stdio: "pipe", maxBuffer: 64 * 1024 * 1024 });

  if (result.status !== 0) {
    const stderr = result.stderr?.toString() || "";
    throw new Error(`FFmpeg encoding failed:\n${stderr.slice(-2000)}`);
  }

  // Cleanup frames dir
  try {
    fs.readdirSync(framesDir).forEach(f => fs.unlinkSync(path.join(framesDir, f)));
    fs.rmdirSync(framesDir);
  } catch {}

  console.log(`[render] Done: ${outputLocation}`);
}

main().catch((err) => {
  console.error("[render] FATAL:", err);
  process.exit(1);
});
