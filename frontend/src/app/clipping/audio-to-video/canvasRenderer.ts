// ─── Canvas 2D Renderer ─────────────────────────────────────────────────────
// Programmatically renders the 9:16 HTML preview into a canvas at 1080×1920,
// replicating every Framer Motion animation with time-driven math so
// MediaRecorder can capture it as a smooth video.
// ─────────────────────────────────────────────────────────────────────────────

/* ── Types ────────────────────────────────────────────────────────────────── */

export interface AudioWord {
  id?: number;
  word: string;
  start_s: number;
  end_s: number;
}

export interface ThemeColors {
  accent: string;
  textGlow: string;
}

export type ThemeId = "minimal" | "vivid" | "neon" | "inferno";

export interface RendererConfig {
  width: number;             // 1080
  height: number;            // 1920
  themeId: ThemeId;
  theme: ThemeColors;
  words: AudioWord[];
  bgImageUrl: string | null;
  coverImageUrl: string | null;
  clipStartS: number;        // absolute start of clip in full track
  clipDuration: number;       // seconds
}

export interface CanvasRenderer {
  canvas: HTMLCanvasElement;
  renderFrame(audioCurrentTime: number): void;
  destroy(): void;
}

/* ── Helpers ──────────────────────────────────────────────────────────────── */

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  ];
}

const THEME_DARK_RGB: Record<string, [number, number, number]> = {
  minimal: [8, 10, 14],
  vivid: [18, 0, 26],
  neon: [0, 0, 0],
  inferno: [10, 8, 8],
};

/** Sinusoidal ease-in-out for pulse animations */
function pulse(t: number, period: number, amp: number): number {
  return amp * Math.sin((2 * Math.PI * t) / period);
}

/** Keyframe interpolation for arrays like [0, 60, -60, 0] over duration D */
function keyframeLerp(t: number, duration: number, values: number[]): number {
  const phase = ((t % duration) + duration) % duration;
  const segCount = values.length - 1;
  const segDur = duration / segCount;
  const segIdx = Math.min(Math.floor(phase / segDur), segCount - 1);
  const segT = (phase - segIdx * segDur) / segDur;
  return values[segIdx] + (values[segIdx + 1] - values[segIdx]) * segT;
}

/** Rounded-rect path helper */
function roundedRect(
  ctx: CanvasRenderingContext2D,
  x: number, y: number, w: number, h: number, r: number,
) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + r);
  ctx.lineTo(x + w, y + h - r);
  ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  ctx.lineTo(x + r, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
}

/* ── Particle / Flame seeds ───────────────────────────────────────────────── */

interface ParticleSeed {
  x: number;       // 0–1 fraction of width
  size: number;     // px
  speed: number;    // px per second
  delay: number;    // seconds
  period: number;   // loop period in seconds
  xDrift: number;   // px per second horizontal drift
}

interface FlameSeed {
  x: number;        // 0–1 fraction of width (10%–90%)
  w: number;        // px
  h: number;        // px
  speed: number;    // px per second
  delay: number;    // seconds
  period: number;   // loop period
}

function makeParticleSeeds(count: number): ParticleSeed[] {
  const seeds: ParticleSeed[] = [];
  for (let i = 0; i < count; i++) {
    seeds.push({
      x: Math.random(),
      size: Math.random() * 4 + 1,
      speed: (800 + Math.random() * 400) / (Math.random() * 4 + 4),
      delay: Math.random() * 4,
      period: Math.random() * 4 + 4,
      xDrift: (Math.random() - 0.5) * 100 / (Math.random() * 4 + 4),
    });
  }
  return seeds;
}

function makeFlameSeedsList(count: number): FlameSeed[] {
  const seeds: FlameSeed[] = [];
  for (let i = 0; i < count; i++) {
    seeds.push({
      x: Math.random() * 0.8 + 0.1,
      w: Math.random() * 60 + 40,
      h: Math.random() * 100 + 80,
      speed: (400 + Math.random() * 300) / (Math.random() * 2 + 1.5),
      delay: Math.random() * 2,
      period: Math.random() * 2 + 1.5,
    });
  }
  return seeds;
}

/* ── Load image helper ────────────────────────────────────────────────────── */

function loadImage(src: string): Promise<HTMLImageElement | null> {
  return new Promise((resolve) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = src;
  });
}

/* ── Factory ──────────────────────────────────────────────────────────────── */

export async function createCanvasRenderer(
  cfg: RendererConfig,
): Promise<CanvasRenderer> {
  const { width: CW, height: CH, themeId: tid, theme, words } = cfg;
  const [acR, acG, acB] = hexToRgb(theme.accent);
  const dark = THEME_DARK_RGB[tid] ?? [8, 10, 14];

  // ── Layout constants (derived from HTML CSS %) ──────────────────────────
  const CARD_X = Math.round(CW * 0.08);
  const CARD_Y = Math.round(CH * 0.06);
  const CARD_W = CW - 2 * CARD_X;
  const CARD_H = Math.round(CH * 0.46);
  const CARD_R = 60; // ~2rem at this scale
  const CARD_CX = CARD_X + CARD_W / 2;
  const CARD_CY = CARD_Y + CARD_H / 2;

  // Art area inside card (with padding ~24px each side)
  const ART_PAD = 48;
  const ART_X = CARD_X + ART_PAD;
  const ART_Y = CARD_Y + ART_PAD;
  const ART_W = CARD_W - 2 * ART_PAD;
  const ART_H = CARD_H - 2 * ART_PAD - 80; // leave room for NOW PLAYING label
  const ART_CX = ART_X + ART_W / 2;
  const ART_CY = ART_Y + ART_H / 2;
  const ART_R = Math.min(ART_W, ART_H) / 2;

  // Zigzag waveform position
  const ZIG_X = Math.round(CW * 0.13);
  const ZIG_Y = Math.round(CH * 0.588);
  const ZIG_W = Math.round(CW * 0.74);
  const ZIG_H = 30;

  // Karaoke lyrics position
  const LYRIC_Y = Math.round(CH * 0.80);

  const GROUP_SZ = 5;

  // ── Pre-render: blurred background ──────────────────────────────────────
  const bgCanvas = document.createElement("canvas");
  bgCanvas.width = CW;
  bgCanvas.height = CH;
  const bgCtx = bgCanvas.getContext("2d")!;

  if (cfg.bgImageUrl) {
    const bgImg = await loadImage(cfg.bgImageUrl);
    if (bgImg) {
      const ratio = bgImg.width / bgImg.height;
      let dw = CW, dh = CH;
      if (ratio > CW / CH) { dh = CH; dw = ratio * CH; }
      else { dw = CW; dh = CW / ratio; }
      bgCtx.filter = "blur(32px)";
      bgCtx.drawImage(bgImg, (CW - dw) / 2, (CH - dh) / 2, dw, dh);
      bgCtx.filter = "none";
      if (tid === "inferno") {
        bgCtx.fillStyle = "rgba(0,0,0,0.45)";
        bgCtx.fillRect(0, 0, CW, CH);
      }
    } else {
      bgCtx.fillStyle = `rgb(${dark[0]},${dark[1]},${dark[2]})`;
      bgCtx.fillRect(0, 0, CW, CH);
    }
  } else {
    bgCtx.fillStyle = `rgb(${dark[0]},${dark[1]},${dark[2]})`;
    bgCtx.fillRect(0, 0, CW, CH);
  }

  // ── Pre-render: circular album cover ────────────────────────────────────
  const coverR = Math.round(ART_R * 0.45 / 0.5); // ~45% of art area
  const coverD = coverR * 2;
  const coverCanvas = document.createElement("canvas");
  coverCanvas.width = coverD;
  coverCanvas.height = coverD;
  const covCtx = coverCanvas.getContext("2d")!;
  let hasCover = false;

  if (cfg.coverImageUrl) {
    const covImg = await loadImage(cfg.coverImageUrl);
    if (covImg) {
      hasCover = true;
      const ratio = covImg.width / covImg.height;
      let dw: number, dh: number;
      if (ratio > 1) { dh = coverD; dw = ratio * coverD; }
      else { dw = coverD; dh = coverD / ratio; }
      covCtx.save();
      covCtx.beginPath();
      covCtx.arc(coverR, coverR, coverR, 0, Math.PI * 2);
      covCtx.clip();
      covCtx.drawImage(covImg, (coverD - dw) / 2, (coverD - dh) / 2, dw, dh);
      covCtx.restore();
    }
  }

  // ── Pre-render: square album cover for vivid/inferno ────────────────────
  const sqSize = Math.round(ART_R * 1.1); // 55% of art dimensions
  const sqCanvas = document.createElement("canvas");
  sqCanvas.width = sqSize;
  sqCanvas.height = sqSize;
  const sqCtx = sqCanvas.getContext("2d")!;
  let hasSquareCover = false;

  if (cfg.coverImageUrl) {
    const sqImg = await loadImage(cfg.coverImageUrl);
    if (sqImg) {
      hasSquareCover = true;
      const ratio = sqImg.width / sqImg.height;
      let dw: number, dh: number;
      if (ratio > 1) { dh = sqSize; dw = ratio * sqSize; }
      else { dw = sqSize; dh = sqSize / ratio; }
      sqCtx.drawImage(sqImg, (sqSize - dw) / 2, (sqSize - dh) / 2, dw, dh);
    }
  }

  // ── Pre-render: grayscale cover for inferno ─────────────────────────────
  const infernoSqSize = Math.round(ART_W * 0.70);
  const infernoCanvas = document.createElement("canvas");
  infernoCanvas.width = infernoSqSize;
  infernoCanvas.height = infernoSqSize;
  const infernoCtx = infernoCanvas.getContext("2d")!;

  if (cfg.coverImageUrl) {
    const infImg = await loadImage(cfg.coverImageUrl);
    if (infImg) {
      const ratio = infImg.width / infImg.height;
      let dw: number, dh: number;
      if (ratio > 1) { dh = infernoSqSize; dw = ratio * infernoSqSize; }
      else { dw = infernoSqSize; dh = infernoSqSize / ratio; }
      infernoCtx.filter = "grayscale(1) contrast(1.25)";
      infernoCtx.globalAlpha = 0.9;
      infernoCtx.drawImage(infImg, (infernoSqSize - dw) / 2, (infernoSqSize - dh) / 2, dw, dh);
      infernoCtx.filter = "none";
      infernoCtx.globalAlpha = 1;
      // Bottom fade
      const grad = infernoCtx.createLinearGradient(0, infernoSqSize * 0.5, 0, infernoSqSize);
      grad.addColorStop(0, "rgba(0,0,0,0)");
      grad.addColorStop(1, "rgba(0,0,0,0.8)");
      infernoCtx.fillStyle = grad;
      infernoCtx.fillRect(0, 0, infernoSqSize, infernoSqSize);
    }
  }

  // ── Pre-compute: seeds ──────────────────────────────────────────────────
  const particleSeeds = makeParticleSeeds(20);
  const flameSeeds = makeFlameSeedsList(15);

  // ── Pre-compute: word groups ────────────────────────────────────────────
  const groups: AudioWord[][] = [];
  for (let i = 0; i < words.length; i += GROUP_SZ) {
    groups.push(words.slice(i, i + GROUP_SZ));
  }

  // ── Pre-compute: zigzag path points ─────────────────────────────────────
  const zigzagPoints: Array<[number, number]> = [[0, 15]];
  for (let i = 0; i < 80; i++) {
    const x = ((i + 1) / 80) * ZIG_W;
    const y = i % 2 === 0 ? 5 : 25;
    zigzagPoints.push([x, y]);
  }

  // ── Recording canvas ───────────────────────────────────────────────────
  const canvas = document.createElement("canvas");
  canvas.width = CW;
  canvas.height = CH;
  const ctx = canvas.getContext("2d")!;

  // ══════════════════════════════════════════════════════════════════════════
  //  DRAW FUNCTIONS
  // ══════════════════════════════════════════════════════════════════════════

  function drawBackground() {
    ctx.drawImage(bgCanvas, 0, 0);
  }

  function drawGradientOverlay() {
    const grad = ctx.createLinearGradient(0, 0, 0, CH);
    grad.addColorStop(0, `rgba(${dark[0]},${dark[1]},${dark[2]},0.88)`);
    grad.addColorStop(0.44, `rgba(${dark[0]},${dark[1]},${dark[2]},0.20)`);
    grad.addColorStop(0.56, `rgba(${dark[0]},${dark[1]},${dark[2]},0.20)`);
    grad.addColorStop(1, `rgba(${dark[0]},${dark[1]},${dark[2]},0.90)`);
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, CW, CH);

    // Extra dark bands matching HTML: from-black/60 via-transparent to-black/80
    const grad2 = ctx.createLinearGradient(0, 0, 0, CH);
    grad2.addColorStop(0, "rgba(0,0,0,0.60)");
    grad2.addColorStop(0.4, "rgba(0,0,0,0)");
    grad2.addColorStop(0.6, "rgba(0,0,0,0)");
    grad2.addColorStop(1, "rgba(0,0,0,0.80)");
    ctx.fillStyle = grad2;
    ctx.fillRect(0, 0, CW, CH);
  }

  function drawTemplateTints() {
    if (tid === "vivid") {
      // Pink blob top-left
      const rg = ctx.createRadialGradient(-200, -200, 0, -200, -200, 700);
      rg.addColorStop(0, "rgba(255,90,200,0.22)");
      rg.addColorStop(1, "rgba(255,90,200,0)");
      ctx.fillStyle = rg;
      ctx.fillRect(0, 0, CW, CH);
    } else if (tid === "neon") {
      // Subtle cyan tint
      const rg = ctx.createRadialGradient(CW / 2, CH * 0.3, 0, CW / 2, CH * 0.3, 800);
      rg.addColorStop(0, "rgba(0,220,255,0.08)");
      rg.addColorStop(1, "rgba(0,220,255,0)");
      ctx.fillStyle = rg;
      ctx.fillRect(0, 0, CW, CH);
    }
  }

  function drawParticles(t: number) {
    ctx.save();
    ctx.globalCompositeOperation = "screen";
    for (const s of particleSeeds) {
      const elapsed = ((t - s.delay) % s.period + s.period) % s.period;
      const progress = elapsed / s.period;
      const px = s.x * CW + s.xDrift * elapsed;
      const py = CH - s.speed * elapsed;
      // Fade: 0→0.8 in first 30%, then 0.8→0 in remaining 70%
      let opacity: number;
      if (progress < 0.3) opacity = (progress / 0.3) * 0.8;
      else opacity = 0.8 * (1 - (progress - 0.3) / 0.7);
      if (opacity <= 0 || py < -20) continue;

      ctx.globalAlpha = opacity;
      ctx.fillStyle = `rgb(${acR},${acG},${acB})`;
      ctx.beginPath();
      ctx.arc(px, py, s.size / 2, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = "source-over";
    ctx.restore();
  }

  function drawFlames(t: number) {
    ctx.save();
    ctx.globalCompositeOperation = "screen";
    ctx.globalAlpha = 0.70; // match HTML opacity-70

    for (const s of flameSeeds) {
      const elapsed = ((t - s.delay) % s.period + s.period) % s.period;
      const progress = elapsed / s.period;
      const px = s.x * CW;
      const py = CH + CH * 0.1 - s.speed * elapsed;

      // Scale: scaleY 1→2.5, scaleX 1→0.5
      const scaleY = 1 + 1.5 * progress;
      const scaleX = 1 - 0.5 * progress;

      // Opacity: 0→0.6→0 (peak around 40%)
      let opacity: number;
      if (progress < 0.4) opacity = (progress / 0.4) * 0.6;
      else opacity = 0.6 * (1 - (progress - 0.4) / 0.6);
      if (opacity <= 0) continue;

      const w = s.w * scaleX;
      const h = s.h * scaleY;

      ctx.globalAlpha = 0.70 * opacity;
      ctx.fillStyle = "white";
      ctx.beginPath();
      // Approximate blur-2xl rounded ellipse
      ctx.ellipse(px, py, w / 2, h / 2, 0, 0, Math.PI * 2);
      ctx.fill();
    }

    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = "source-over";
    ctx.restore();
  }

  function drawCard() {
    ctx.save();

    // Card background — semi-transparent fill (skip backdrop-blur for perf)
    roundedRect(ctx, CARD_X, CARD_Y, CARD_W, CARD_H, CARD_R);

    if (tid === "minimal") {
      ctx.fillStyle = "rgba(255,255,255,0.05)";
    } else if (tid === "vivid") {
      ctx.fillStyle = "rgba(112,26,80,0.20)";
    } else if (tid === "neon") {
      ctx.fillStyle = "rgba(0,0,0,0.60)";
    } else {
      ctx.fillStyle = "rgba(0,0,0,0.40)";
    }
    ctx.fill();

    // Card border
    roundedRect(ctx, CARD_X, CARD_Y, CARD_W, CARD_H, CARD_R);
    if (tid === "minimal") {
      ctx.strokeStyle = "rgba(255,255,255,0.10)";
    } else if (tid === "vivid") {
      ctx.strokeStyle = "rgba(255,90,200,0.30)";
    } else if (tid === "neon") {
      ctx.strokeStyle = "rgba(0,220,255,0.40)";
    } else {
      ctx.strokeStyle = "rgba(255,255,255,0.20)";
    }
    ctx.lineWidth = 2;
    ctx.stroke();

    // Card glow (subtle shadow)
    if (tid === "neon") {
      ctx.shadowColor = "rgba(0,220,255,0.3)";
      ctx.shadowBlur = 40;
      roundedRect(ctx, CARD_X, CARD_Y, CARD_W, CARD_H, CARD_R);
      ctx.strokeStyle = "rgba(0,220,255,0.15)";
      ctx.lineWidth = 1;
      ctx.stroke();
      ctx.shadowBlur = 0;
    }

    ctx.restore();
  }

  // ── Template Art Functions ──────────────────────────────────────────────

  function drawMinimalArt(t: number) {
    ctx.save();

    // Outer dashed ring — rotating CW, duration=20s
    const outerR = ART_R * 0.85;
    const angle1 = ((t * 360) / 20) % 360;
    ctx.save();
    ctx.translate(ART_CX, ART_CY);
    ctx.rotate((angle1 * Math.PI) / 180);
    ctx.beginPath();
    ctx.arc(0, 0, outerR, 0, Math.PI * 2);
    ctx.setLineDash([12, 8]);
    ctx.strokeStyle = "rgba(0,255,170,0.50)";
    ctx.lineWidth = 1;
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.restore();

    // Inner solid ring — rotating CCW, duration=15s
    const innerR = ART_R * 0.65;
    const angle2 = -((t * 360) / 15) % 360;
    ctx.save();
    ctx.translate(ART_CX, ART_CY);
    ctx.rotate((angle2 * Math.PI) / 180);
    ctx.beginPath();
    ctx.arc(0, 0, innerR, 0, Math.PI * 2);
    ctx.strokeStyle = "rgba(0,255,170,0.40)";
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.restore();

    // Center glow
    const glowR = ctx.createRadialGradient(ART_CX, ART_CY, 0, ART_CX, ART_CY, ART_R * 0.40);
    glowR.addColorStop(0, "rgba(0,255,170,0.20)");
    glowR.addColorStop(1, "rgba(0,255,170,0)");
    ctx.fillStyle = glowR;
    ctx.beginPath();
    ctx.arc(ART_CX, ART_CY, ART_R * 0.40, 0, Math.PI * 2);
    ctx.fill();

    // Album cover circle — pulsing scale 1→1.03→1 over 1.5s
    const coverScale = 1 + 0.03 * Math.sin((2 * Math.PI * t) / 1.5);
    const drawR = coverR * coverScale;

    if (hasCover) {
      ctx.save();
      ctx.beginPath();
      ctx.arc(ART_CX, ART_CY, drawR, 0, Math.PI * 2);
      ctx.clip();
      ctx.drawImage(coverCanvas, ART_CX - drawR, ART_CY - drawR, drawR * 2, drawR * 2);
      ctx.restore();

      // Border + glow
      ctx.beginPath();
      ctx.arc(ART_CX, ART_CY, drawR, 0, Math.PI * 2);
      ctx.strokeStyle = "rgba(255,255,255,0.20)";
      ctx.lineWidth = 3;
      ctx.shadowColor = "rgba(0,255,170,0.3)";
      ctx.shadowBlur = 30;
      ctx.stroke();
      ctx.shadowBlur = 0;
    } else {
      ctx.beginPath();
      ctx.arc(ART_CX, ART_CY, drawR, 0, Math.PI * 2);
      ctx.fillStyle = "rgba(0,255,170,0.08)";
      ctx.fill();
      ctx.strokeStyle = "rgba(0,255,170,0.30)";
      ctx.lineWidth = 3;
      ctx.stroke();
    }

    ctx.restore();
  }

  function drawVividArt(t: number) {
    ctx.save();

    // Inner card area clipping
    const innerR = 45; // ~1.5rem
    ctx.save();
    roundedRect(ctx, ART_X - 24, ART_Y - 24, ART_W + 48, ART_H + 48, innerR);
    ctx.clip();

    // Floating pink blob (top-left) — keyframed x,y,scale over 5s
    const blobX1 = keyframeLerp(t, 5, [0, 60, -60, 0]);
    const blobY1 = keyframeLerp(t, 5, [0, -80, 60, 0]);
    const blobS1 = keyframeLerp(t, 5, [1, 1.5, 1, 1]);
    const blobCX1 = ART_X + blobX1;
    const blobCY1 = ART_Y + blobY1;
    const blobR1 = 96 * blobS1;
    const g1 = ctx.createRadialGradient(blobCX1, blobCY1, 0, blobCX1, blobCY1, blobR1);
    g1.addColorStop(0, "rgba(255,90,200,0.70)");
    g1.addColorStop(1, "rgba(255,90,200,0)");
    ctx.fillStyle = g1;
    ctx.fillRect(ART_X - 100, ART_Y - 100, ART_W + 200, ART_H + 200);

    // Floating purple blob (bottom-right) — keyframed x,y,scale over 4s
    const blobX2 = keyframeLerp(t, 4, [0, -80, 40, 0]);
    const blobY2 = keyframeLerp(t, 4, [0, 60, -80, 0]);
    const blobS2 = keyframeLerp(t, 4, [1, 1.2, 1, 1]);
    const blobCX2 = ART_X + ART_W + blobX2;
    const blobCY2 = ART_Y + ART_H + blobY2;
    const blobR2 = 112 * blobS2;
    const g2 = ctx.createRadialGradient(blobCX2, blobCY2, 0, blobCX2, blobCY2, blobR2);
    g2.addColorStop(0, "rgba(168,85,247,0.70)");
    g2.addColorStop(1, "rgba(168,85,247,0)");
    ctx.fillStyle = g2;
    ctx.fillRect(ART_X - 100, ART_Y - 100, ART_W + 200, ART_H + 200);

    ctx.restore(); // un-clip

    // Album cover — rounded rect, pulsing scale 1→1.15→1 over 0.6s
    const vividScale = 1 + 0.15 * Math.sin((2 * Math.PI * t) / 0.6);
    const vividSz = Math.round(ART_R * 1.1) * vividScale;
    const vividR = 36; // ~1.2rem
    const vx = ART_CX - vividSz / 2;
    const vy = ART_CY - vividSz / 2;

    ctx.save();
    // Glow
    ctx.shadowColor = "rgba(255,90,200,0.6)";
    ctx.shadowBlur = 40;

    roundedRect(ctx, vx, vy, vividSz, vividSz, vividR);
    ctx.clip();

    if (hasSquareCover) {
      ctx.drawImage(sqCanvas, vx, vy, vividSz, vividSz);
    } else {
      ctx.fillStyle = "rgba(255,255,255,0.10)";
      ctx.fillRect(vx, vy, vividSz, vividSz);
    }

    // Pink gradient overlay
    const pg = ctx.createLinearGradient(vx, vy, vx + vividSz, vy);
    pg.addColorStop(0, "rgba(255,90,200,0.30)");
    pg.addColorStop(1, "rgba(255,90,200,0)");
    ctx.fillStyle = pg;
    ctx.fillRect(vx, vy, vividSz, vividSz);

    ctx.restore();

    // Border
    roundedRect(ctx, vx, vy, vividSz, vividSz, vividR);
    ctx.strokeStyle = "rgba(255,255,255,0.30)";
    ctx.lineWidth = 3;
    ctx.stroke();

    ctx.restore();
  }

  function drawNeonArt(t: number) {
    ctx.save();

    // Conic-gradient spinner — rotating at 360/15 = 24°/s
    const spinAngle = ((t * 360) / 15) % 360;
    const spinR = ART_R * 0.95;

    // Draw a rotating line to simulate the conic gradient sweep
    ctx.save();
    ctx.translate(ART_CX, ART_CY);
    ctx.rotate((spinAngle * Math.PI) / 180);
    // Draw a faded arc segment
    for (let i = 0; i < 20; i++) {
      const a = (i / 20) * (20 * Math.PI / 180); // 20-degree sweep
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.arc(0, 0, spinR, a, a + (Math.PI / 180));
      ctx.closePath();
      ctx.fillStyle = `rgba(0,220,255,${0.4 * (1 - i / 20)})`;
      ctx.fill();
    }
    ctx.restore();

    // Vinyl disc — rotating at 360/5 = 72°/s
    const discAngle = ((t * 360) / 5) % 360;
    const discR = ART_R * 0.85;

    ctx.save();
    ctx.translate(ART_CX, ART_CY);
    ctx.rotate((discAngle * Math.PI) / 180);

    // Disc fill
    ctx.beginPath();
    ctx.arc(0, 0, discR, 0, Math.PI * 2);
    ctx.fillStyle = "rgb(10,10,10)";
    ctx.fill();

    // Disc border
    ctx.beginPath();
    ctx.arc(0, 0, discR, 0, Math.PI * 2);
    ctx.strokeStyle = "rgba(0,220,255,0.50)";
    ctx.lineWidth = 2;
    ctx.shadowColor = "rgba(0,220,255,0.4)";
    ctx.shadowBlur = 50;
    ctx.stroke();
    ctx.shadowBlur = 0;

    // Concentric groove rings — inset 2,6,10,14 (scaled)
    const insets = [0.05, 0.15, 0.25, 0.35];
    for (const ins of insets) {
      ctx.beginPath();
      ctx.arc(0, 0, discR * (1 - ins), 0, Math.PI * 2);
      ctx.strokeStyle = "rgba(255,255,255,0.10)";
      ctx.lineWidth = 1;
      ctx.stroke();
    }

    // Center album cover
    const neonCoverR = discR * 0.45 / 0.85 * 0.45 * 2; // ~45% of disc = album label
    const nCR = discR * 0.265;
    ctx.beginPath();
    ctx.arc(0, 0, nCR, 0, Math.PI * 2);
    ctx.clip();
    if (hasCover) {
      ctx.drawImage(coverCanvas, -nCR, -nCR, nCR * 2, nCR * 2);
    } else {
      ctx.fillStyle = "rgba(255,255,255,0.10)";
      ctx.fill();
    }

    ctx.restore();

    // Center dot
    ctx.beginPath();
    ctx.arc(ART_CX, ART_CY, 8, 0, Math.PI * 2);
    ctx.fillStyle = "rgb(0,0,0)";
    ctx.fill();
    ctx.strokeStyle = "rgba(0,220,255,0.60)";
    ctx.lineWidth = 2;
    ctx.shadowColor = "rgba(0,220,255,1)";
    ctx.shadowBlur = 15;
    ctx.stroke();
    ctx.shadowBlur = 0;

    ctx.restore();
  }

  function drawInfernoArt(t: number) {
    ctx.save();

    // Flames inside art area
    ctx.save();
    roundedRect(ctx, ART_X - 24, ART_Y - 24, ART_W + 48, ART_H + 48, 60);
    ctx.clip();
    drawFlames(t); // reuse the flame drawing
    ctx.restore();

    // Bobbing y: 0→-10→0 over 2s
    const bobY = -10 * Math.sin((2 * Math.PI * t) / 2);

    // Square album cover with white border
    const sqSz = infernoSqSize;
    const sx = ART_CX - sqSz / 2;
    const sy = ART_CY - sqSz / 2 + bobY;

    // Box shadow pulse: glow 0.1→0.4→0.1 over 2s
    const shadowAlpha = 0.1 + 0.3 * Math.abs(Math.sin((2 * Math.PI * t) / 2));
    ctx.shadowColor = `rgba(255,255,255,${shadowAlpha})`;
    ctx.shadowBlur = 40 + 20 * Math.abs(Math.sin((2 * Math.PI * t) / 2));

    // Border
    ctx.fillStyle = "rgba(0,0,0,1)";
    ctx.fillRect(sx - 4, sy - 4, sqSz + 8, sqSz + 8);
    ctx.strokeStyle = "rgba(255,255,255,0.30)";
    ctx.lineWidth = 2;
    ctx.strokeRect(sx - 4, sy - 4, sqSz + 8, sqSz + 8);

    ctx.shadowBlur = 0;

    // Draw grayscale cover
    if (cfg.coverImageUrl) {
      ctx.drawImage(infernoCanvas, sx, sy, sqSz, sqSz);
    } else {
      ctx.fillStyle = "rgba(255,255,255,0.10)";
      ctx.fillRect(sx, sy, sqSz, sqSz);
    }

    ctx.restore();
  }

  function drawNowPlaying() {
    const labelY = CARD_Y + CARD_H - 40;
    ctx.save();
    ctx.font = "bold 20px -apple-system, 'Segoe UI', sans-serif";
    ctx.textBaseline = "middle";
    ctx.fillStyle = "rgba(255,255,255,0.50)";

    // Manual letter spacing (6px between each character)
    const text = "NOW PLAYING";
    const spacing = 6;
    let totalW = 0;
    for (const ch of text) totalW += ctx.measureText(ch).width + spacing;
    totalW -= spacing; // no spacing after last char
    let cx = CW / 2 - totalW / 2;
    for (const ch of text) {
      ctx.fillText(ch, cx, labelY);
      cx += ctx.measureText(ch).width + spacing;
    }

    ctx.restore();
  }

  function drawZigzagWaveform(audioTime: number) {
    const progress = Math.min(1, Math.max(0, audioTime / cfg.clipDuration));

    ctx.save();
    ctx.translate(ZIG_X, ZIG_Y - ZIG_H / 2);

    // Background dimmed zigzag
    ctx.beginPath();
    ctx.moveTo(zigzagPoints[0][0], zigzagPoints[0][1]);
    for (let i = 1; i < zigzagPoints.length; i++) {
      ctx.lineTo(zigzagPoints[i][0], zigzagPoints[i][1]);
    }
    ctx.strokeStyle = "rgba(255,255,255,0.15)";
    ctx.lineWidth = 4;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.stroke();

    // Foreground colored zigzag (clipped to progress)
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, ZIG_W * progress, ZIG_H);
    ctx.clip();

    ctx.beginPath();
    ctx.moveTo(zigzagPoints[0][0], zigzagPoints[0][1]);
    for (let i = 1; i < zigzagPoints.length; i++) {
      ctx.lineTo(zigzagPoints[i][0], zigzagPoints[i][1]);
    }
    ctx.strokeStyle = `rgb(${acR},${acG},${acB})`;
    ctx.lineWidth = 4;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.shadowColor = `rgba(${acR},${acG},${acB},0.6)`;
    ctx.shadowBlur = 6;
    ctx.stroke();
    ctx.shadowBlur = 0;
    ctx.restore();

    ctx.restore();
  }

  function drawKaraokeLyrics(audioTime: number) {
    const tAbs = audioTime + (cfg.clipStartS ?? 0);

    // Find current word index using "last started word" algorithm
    let wi = -1;
    for (let i = 0; i < words.length; i++) {
      if (words[i].start_s <= tAbs) wi = i;
      else break;
    }

    const gi = wi >= 0 ? Math.floor(wi / GROUP_SZ) : 0;
    const grp = groups[gi] ?? [];
    const li = wi >= 0 ? wi - gi * GROUP_SZ : -1;

    if (grp.length === 0) return;

    let fs = 80;
    ctx.font = `bold ${fs}px -apple-system, "Segoe UI", sans-serif`;
    ctx.textBaseline = "middle";

    const parts = grp.map((w, i) => w.word + (i < grp.length - 1 ? " " : ""));
    let tw = parts.reduce((s, p) => s + ctx.measureText(p).width, 0);

    if (tw > CW * 0.87) {
      fs = Math.floor(fs * (CW * 0.87) / tw);
      ctx.font = `bold ${fs}px -apple-system, "Segoe UI", sans-serif`;
      tw = parts.reduce((s, p) => s + ctx.measureText(p).width, 0);
    }

    let x = CW / 2 - tw / 2;
    const y = LYRIC_Y;

    ctx.save();
    parts.forEach((p, i) => {
      const pw = ctx.measureText(p).width;
      if (i === li) {
        // Current word — accent color + glow
        ctx.fillStyle = `rgb(${acR},${acG},${acB})`;
        ctx.shadowColor = `rgba(${acR},${acG},${acB},0.75)`;
        ctx.shadowBlur = 28;
      } else if (i < li) {
        // Passed word — dimmed white
        ctx.fillStyle = "rgba(255,255,255,0.40)";
        ctx.shadowBlur = 0;
      } else {
        // Upcoming word — bright white with dark shadow
        ctx.fillStyle = "rgba(255,255,255,0.88)";
        ctx.shadowColor = "rgba(0,0,0,0.8)";
        ctx.shadowBlur = 10;
      }
      ctx.fillText(p, x, y);
      x += pw;
      ctx.shadowBlur = 0;
    });
    ctx.restore();
  }

  // ══════════════════════════════════════════════════════════════════════════
  //  PUBLIC API
  // ══════════════════════════════════════════════════════════════════════════

  function renderFrame(audioCurrentTime: number) {
    ctx.clearRect(0, 0, CW, CH);

    // 1. Background
    drawBackground();

    // 2. Gradient overlay
    drawGradientOverlay();

    // 3. Template colour tints
    drawTemplateTints();

    // 4. Particles or Flames (behind card)
    if (tid === "inferno") {
      drawFlames(audioCurrentTime);
    } else {
      drawParticles(audioCurrentTime);
    }

    // 5. Card container
    drawCard();

    // 6. Template art inside card
    switch (tid) {
      case "minimal":
        drawMinimalArt(audioCurrentTime);
        break;
      case "vivid":
        drawVividArt(audioCurrentTime);
        break;
      case "neon":
        drawNeonArt(audioCurrentTime);
        break;
      case "inferno":
        drawInfernoArt(audioCurrentTime);
        break;
    }

    // 7. "NOW PLAYING" label
    drawNowPlaying();

    // 8. Zigzag waveform
    drawZigzagWaveform(audioCurrentTime);

    // 9. Karaoke lyrics
    drawKaraokeLyrics(audioCurrentTime);
  }

  function destroy() {
    // Help GC by clearing references
    bgCanvas.width = 0;
    bgCanvas.height = 0;
    coverCanvas.width = 0;
    coverCanvas.height = 0;
    sqCanvas.width = 0;
    sqCanvas.height = 0;
    infernoCanvas.width = 0;
    infernoCanvas.height = 0;
  }

  return { canvas, renderFrame, destroy };
}
