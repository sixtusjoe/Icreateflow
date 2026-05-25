#!/usr/bin/env node
/**
 * Standalone Remotion render script.
 * Called by the backend to render a video from the AudioVideo composition.
 *
 * Usage:
 *   node render.mjs --props '{"themeId":"minimal",...}' --output /path/to/out.mp4 --duration 30
 */
import { bundle } from "@remotion/bundler";
import { renderMedia, selectComposition } from "@remotion/renderer";
import path from "path";
import fs from "fs";
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
  return null; // let Remotion find/download its own
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

  console.log(
    `[render] Rendering ${durationInFrames} frames (${durationSec}s @ ${fps}fps) → ${outputLocation}`
  );

  // Ensure output directory exists
  const outDir = path.dirname(outputLocation);
  if (!fs.existsSync(outDir)) {
    fs.mkdirSync(outDir, { recursive: true });
  }

  await renderMedia({
    composition,
    serveUrl: bundleLocation,
    codec: "h264",
    outputLocation,
    inputProps,
    ...(chromiumPath ? { browserExecutable: chromiumPath } : {}),
    chromiumOptions: {
      gl: "swangle",
      disableWebSecurity: true, // allow loading local file URLs
      // Multi-process mode prevents the recurring --single-process crashes
      // that happen every ~9 frames on Linux servers.
      // We have 5+ GB free RAM so the extra cost is acceptable.
      enableMultiProcessOnLinux: true,
    },
    // Limit concurrency to 1 to avoid exhausting RAM on low-memory servers.
    // Each parallel frame renders a full Chromium tab — 1 tab per frame at a time.
    concurrency: 1,
    timeoutInMilliseconds: 60000,
    // Lower CRF for faster encode (CRF 28 = good quality, smaller file, faster)
    // Use x264 fast preset to reduce CPU time per frame
    encoderOptions: {
      crf: 23,
      preset: "ultrafast",
    },
    onProgress: ({ progress, renderedFrames, encodedFrames }) => {
      const pct = Math.round(progress * 100);
      process.stdout.write(`[render] Progress: ${pct}% (rendered ${renderedFrames}, encoded ${encodedFrames})\n`);
    },
  });

  console.log(`[render] Done: ${outputLocation}`);
}

main().catch((err) => {
  console.error("[render] FATAL:", err);
  process.exit(1);
});
