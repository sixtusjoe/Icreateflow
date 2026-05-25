#!/usr/bin/env node
/**
 * Standalone Remotion render script.
 * Called by the backend to render a video from the AudioVideo composition.
 *
 * Usage:
 *   node render.mjs --props '{"themeId":"minimal",...}' --output /path/to/out.mp4 --duration 30
 *
 * Renders in chunks of CHUNK_FRAMES frames to prevent headless Chromium
 * memory accumulation that causes "Target closed" crashes every ~9 frames.
 * Each chunk starts a fresh browser; chunks are concatenated by FFmpeg.
 */
import { bundle } from "@remotion/bundler";
import { renderMedia, selectComposition } from "@remotion/renderer";
import path from "path";
import fs from "fs";
import { execSync, spawnSync } from "child_process";
import { fileURLToPath } from "url";
import { parseArgs } from "util";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

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

// Restart Chromium every N frames to prevent memory accumulation.
// Empirically, crashes happen every ~9 frames in --single-process mode.
// Rendering 8 frames per chunk keeps well under that threshold.
const CHUNK_FRAMES = 8;

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

async function renderChunk(bundleLocation, composition, chromiumPath, startFrame, endFrame, chunkPath) {
  await renderMedia({
    composition,
    serveUrl: bundleLocation,
    codec: "h264",
    outputLocation: chunkPath,
    inputProps,
    frameRange: [startFrame, endFrame],
    ...(chromiumPath ? { browserExecutable: chromiumPath } : {}),
    chromiumOptions: {
      gl: "swangle",
      disableWebSecurity: true,
    },
    concurrency: 1,
    timeoutInMilliseconds: 60000,
    encoderOptions: {
      crf: 23,
      preset: "ultrafast",
    },
    onProgress: ({ progress, renderedFrames, encodedFrames }) => {
      // Report global progress across all chunks
      const globalRendered = startFrame + renderedFrames;
      const pct = Math.round((globalRendered / durationInFrames) * 100);
      process.stdout.write(`[render] Progress: ${pct}% (rendered ${globalRendered}, encoded ${startFrame + encodedFrames})\n`);
    },
  });
}

async function main() {
  const chromiumPath = findChromium();
  console.log(`[render] Chromium: ${chromiumPath || "auto-download"}`);

  console.log("[render] Bundling composition...");
  const bundleLocation = await bundle({
    entryPoint: path.resolve(__dirname, "index.ts"),
    webpackOverride: (config) => config,
  });

  console.log("[render] Selecting composition...");
  const composition = await selectComposition({
    serveUrl: bundleLocation,
    id: "AudioVideo",
    inputProps,
    ...(chromiumPath ? { browserExecutable: chromiumPath } : {}),
  });

  // Override duration
  composition.durationInFrames = durationInFrames;
  composition.fps = fps;

  // Ensure output directory exists
  const outDir = path.dirname(outputLocation);
  if (!fs.existsSync(outDir)) {
    fs.mkdirSync(outDir, { recursive: true });
  }

  const totalChunks = Math.ceil(durationInFrames / CHUNK_FRAMES);
  console.log(`[render] Rendering ${durationInFrames} frames (${durationSec}s @ ${fps}fps) in ${totalChunks} chunks → ${outputLocation}`);

  if (totalChunks === 1) {
    // Single chunk — render directly
    await renderChunk(bundleLocation, composition, chromiumPath, 0, durationInFrames - 1, outputLocation);
  } else {
    // Multi-chunk — render each chunk then FFmpeg concat
    const tmpDir = path.join(path.dirname(outputLocation), `.chunks_${Date.now()}`);
    fs.mkdirSync(tmpDir, { recursive: true });
    const chunkPaths = [];

    for (let i = 0; i < totalChunks; i++) {
      const startFrame = i * CHUNK_FRAMES;
      const endFrame = Math.min((i + 1) * CHUNK_FRAMES - 1, durationInFrames - 1);
      const chunkPath = path.join(tmpDir, `chunk_${String(i).padStart(4, "0")}.mp4`);
      console.log(`[render] Chunk ${i + 1}/${totalChunks}: frames ${startFrame}-${endFrame}`);

      // Brief pause between chunks so previous Chromium can fully exit.
      // "Unable to close browser" warnings leave lingering processes that
      // cause "Session closed" errors in the next chunk if we start too soon.
      if (i > 0) {
        await new Promise(r => setTimeout(r, 800));
      }

      // Retry once if the chunk fails (e.g. due to lingering browser cleanup race)
      let chunkDone = false;
      for (let attempt = 0; attempt < 2 && !chunkDone; attempt++) {
        try {
          if (attempt > 0) {
            console.log(`[render] Retrying chunk ${i + 1} (attempt ${attempt + 1})...`);
            await new Promise(r => setTimeout(r, 1500));
          }
          await renderChunk(bundleLocation, composition, chromiumPath, startFrame, endFrame, chunkPath);
          chunkDone = true;
        } catch (chunkErr) {
          if (attempt === 1) throw chunkErr; // propagate on second failure
          console.error(`[render] Chunk ${i + 1} failed (will retry): ${chunkErr.message}`);
        }
      }
      chunkPaths.push(chunkPath);
    }

    // Concatenate chunks with FFmpeg
    console.log(`[render] Concatenating ${totalChunks} chunks...`);
    const concatList = path.join(tmpDir, "concat.txt");
    fs.writeFileSync(concatList, chunkPaths.map(p => `file '${p}'`).join("\n"));
    const ffmpegResult = spawnSync("ffmpeg", [
      "-y",
      "-f", "concat",
      "-safe", "0",
      "-i", concatList,
      "-c", "copy",
      outputLocation,
    ], { stdio: "pipe" });

    if (ffmpegResult.status !== 0) {
      throw new Error(`FFmpeg concat failed:\n${ffmpegResult.stderr?.toString()}`);
    }

    // Cleanup chunk files
    chunkPaths.forEach(p => { try { fs.unlinkSync(p); } catch {} });
    try { fs.unlinkSync(concatList); fs.rmdirSync(tmpDir); } catch {}
  }

  console.log(`[render] Done: ${outputLocation}`);
}

main().catch((err) => {
  console.error("[render] FATAL:", err);
  process.exit(1);
});
