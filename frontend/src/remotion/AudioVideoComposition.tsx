import React, { useMemo } from "react";
import {
  useCurrentFrame,
  useVideoConfig,
  Audio,
  Img,
  interpolate,
  spring,
  AbsoluteFill,
} from "remotion";

/* ── Types ────────────────────────────────────────────────────────────────── */

interface AudioWord {
  word: string;
  start_s: number;
  end_s: number;
}

export interface CompositionProps {
  themeId: "minimal" | "vivid" | "neon" | "inferno";
  accentColor: string;
  textGlow: string;
  bgImageUrl: string | null;
  coverImageUrl: string | null;
  audioUrl: string | null;
  words: AudioWord[];
  clipStartS: number;
  clipDuration: number;
}

/* ── Theme Constants ──────────────────────────────────────────────────────── */

const THEME_DARK: Record<string, string> = {
  minimal: "rgb(8,10,14)",
  vivid: "rgb(18,0,26)",
  neon: "rgb(0,0,0)",
  inferno: "rgb(10,8,8)",
};

const THEME_CARD_BG: Record<string, string> = {
  minimal: "rgba(255,255,255,0.05)",
  vivid: "rgba(112,26,80,0.20)",
  neon: "rgba(0,0,0,0.60)",
  inferno: "rgba(0,0,0,0.40)",
};

const THEME_CARD_BORDER: Record<string, string> = {
  minimal: "rgba(255,255,255,0.10)",
  vivid: "rgba(255,90,200,0.30)",
  neon: "rgba(0,220,255,0.40)",
  inferno: "rgba(255,255,255,0.20)",
};

const THEME_CARD_SHADOW: Record<string, string> = {
  minimal: "0 0 40px rgba(0,255,170,0.05)",
  vivid: "0 0 50px rgba(255,90,200,0.2)",
  neon: "inset 0 0 20px rgba(0,220,255,0.1), 0 0 40px rgba(0,220,255,0.3)",
  inferno: "0 0 30px rgba(255,255,255,0.1)",
};

/* ── Helpers ──────────────────────────────────────────────────────────────── */

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  ];
}

/** Continuous rotation angle in degrees for a given time and period */
function rotAngle(t: number, period: number, dir: 1 | -1 = 1): number {
  return dir * ((t * 360) / period) % 360;
}

/** Sinusoidal pulse between 1-amp and 1+amp */
function pulseSin(t: number, period: number, amp: number): number {
  return 1 + amp * Math.sin((2 * Math.PI * t) / period);
}

/** Keyframe interpolation for values like [0, 60, -60, 0] over duration D */
function keyframeLerp(t: number, duration: number, values: number[]): number {
  const phase = ((t % duration) + duration) % duration;
  const segCount = values.length - 1;
  const segDur = duration / segCount;
  const segIdx = Math.min(Math.floor(phase / segDur), segCount - 1);
  const segT = (phase - segIdx * segDur) / segDur;
  return values[segIdx] + (values[segIdx + 1] - values[segIdx]) * segT;
}

/* ── Seeded random for deterministic particles/flames ─────────────────────── */

function seededRandom(seed: number): () => number {
  let s = seed;
  return () => {
    s = (s * 16807) % 2147483647;
    return (s - 1) / 2147483646;
  };
}

/* ── Particle component ───────────────────────────────────────────────────── */

const Particles: React.FC<{ color: string; t: number }> = ({ color, t }) => {
  const particles = useMemo(() => {
    const rng = seededRandom(42);
    return Array.from({ length: 20 }, () => ({
      x: rng() * 100,
      size: rng() * 4 + 1,
      period: rng() * 4 + 4,
      delay: rng() * 4,
      xDrift: (rng() - 0.5) * 100,
      speedFactor: rng() * 400 + 800,
    }));
  }, []);

  return (
    <div style={{ position: "absolute", inset: 0, overflow: "hidden", mixBlendMode: "screen" }}>
      {particles.map((p, i) => {
        const elapsed = ((t - p.delay) % p.period + p.period) % p.period;
        const progress = elapsed / p.period;
        const yOffset = -(p.speedFactor / p.period) * elapsed;
        const xOffset = (p.xDrift / p.period) * elapsed;
        let opacity = 0;
        if (progress < 0.3) opacity = (progress / 0.3) * 0.8;
        else opacity = 0.8 * (1 - (progress - 0.3) / 0.7);

        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: `${p.x}%`,
              bottom: 0,
              width: p.size,
              height: p.size,
              borderRadius: "50%",
              backgroundColor: color,
              opacity: Math.max(0, opacity),
              transform: `translate(${xOffset}px, ${yOffset}px)`,
            }}
          />
        );
      })}
    </div>
  );
};

/* ── Flame component ──────────────────────────────────────────────────────── */

const Flames: React.FC<{ t: number }> = ({ t }) => {
  const flames = useMemo(() => {
    const rng = seededRandom(99);
    return Array.from({ length: 15 }, () => ({
      x: rng() * 80 + 10,
      w: rng() * 60 + 40,
      h: rng() * 100 + 80,
      period: rng() * 2 + 1.5,
      delay: rng() * 2,
      speedFactor: rng() * 300 + 400,
    }));
  }, []);

  return (
    <div style={{ position: "absolute", inset: 0, overflow: "hidden", mixBlendMode: "screen", opacity: 0.7 }}>
      {flames.map((f, i) => {
        const elapsed = ((t - f.delay) % f.period + f.period) % f.period;
        const progress = elapsed / f.period;
        const yOffset = -(f.speedFactor / f.period) * elapsed;
        const scaleY = 1 + 1.5 * progress;
        const scaleX = 1 - 0.5 * progress;
        let opacity = 0;
        if (progress < 0.4) opacity = (progress / 0.4) * 0.6;
        else opacity = 0.6 * (1 - (progress - 0.4) / 0.6);

        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: `${f.x}%`,
              bottom: "-10%",
              width: f.w,
              height: f.h,
              borderRadius: "100%",
              backgroundColor: "white",
              filter: "blur(24px)",
              opacity: Math.max(0, opacity),
              transform: `translateY(${yOffset}px) scaleX(${scaleX}) scaleY(${scaleY})`,
            }}
          />
        );
      })}
    </div>
  );
};

/* ── Art Components ───────────────────────────────────────────────────────── */

const MinimalArt: React.FC<{ t: number; coverUrl: string | null; accent: string }> = ({
  t, coverUrl, accent,
}) => {
  const outerAngle = rotAngle(t, 20);
  const innerAngle = rotAngle(t, 15, -1);
  const coverScale = pulseSin(t, 1.5, 0.03);

  return (
    <div style={{ position: "relative", width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
      {/* Outer dashed ring */}
      <div
        style={{
          position: "absolute",
          width: "85%", height: "85%",
          borderRadius: "50%",
          border: `0.5px dashed ${accent}80`,
          transform: `rotate(${outerAngle}deg)`,
        }}
      />
      {/* Inner solid ring */}
      <div
        style={{
          position: "absolute",
          width: "65%", height: "65%",
          borderRadius: "50%",
          border: `1px solid ${accent}66`,
          transform: `rotate(${innerAngle}deg)`,
        }}
      />
      {/* Center glow */}
      <div
        style={{
          position: "absolute",
          width: "40%", height: "40%",
          borderRadius: "50%",
          backgroundColor: accent,
          filter: "blur(48px)",
          opacity: 0.20,
        }}
      />
      {/* Album cover */}
      <div
        style={{
          position: "absolute",
          width: "45%", height: "45%",
          borderRadius: "50%",
          overflow: "hidden",
          border: "2px solid rgba(255,255,255,0.2)",
          boxShadow: `0 0 30px ${accent}4D`,
          transform: `scale(${coverScale})`,
        }}
      >
        {coverUrl ? (
          <Img src={coverUrl} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        ) : (
          <div style={{ width: "100%", height: "100%", backgroundColor: "rgba(255,255,255,0.1)", display: "flex", alignItems: "center", justifyContent: "center" }}>
            <div style={{ width: "50%", height: "50%", borderRadius: "50%", border: "2px solid rgba(255,255,255,0.2)" }} />
          </div>
        )}
      </div>
    </div>
  );
};

const VividArt: React.FC<{ t: number; coverUrl: string | null }> = ({ t, coverUrl }) => {
  const blobX1 = keyframeLerp(t, 5, [0, 60, -60, 0]);
  const blobY1 = keyframeLerp(t, 5, [0, -80, 60, 0]);
  const blobS1 = keyframeLerp(t, 5, [1, 1.5, 1, 1]);
  const blobX2 = keyframeLerp(t, 4, [0, -80, 40, 0]);
  const blobY2 = keyframeLerp(t, 4, [0, 60, -80, 0]);
  const blobS2 = keyframeLerp(t, 4, [1, 1.2, 1, 1]);
  const coverScale = pulseSin(t, 0.6, 0.15);

  return (
    <div style={{ position: "relative", width: "100%", height: "100%", borderRadius: "1.5rem", overflow: "hidden", backgroundColor: "rgba(74,4,60,0.40)", border: "1px solid rgba(255,255,255,0.1)", display: "flex", alignItems: "center", justifyContent: "center" }}>
      {/* Pink blob */}
      <div
        style={{
          position: "absolute", top: 0, left: 0,
          width: 192, height: 192,
          backgroundColor: "#FF5AC8",
          borderRadius: "50%",
          filter: "blur(64px)",
          opacity: 0.70,
          transform: `translate(${blobX1}px, ${blobY1}px) scale(${blobS1})`,
        }}
      />
      {/* Purple blob */}
      <div
        style={{
          position: "absolute", bottom: 0, right: 0,
          width: 224, height: 224,
          backgroundColor: "rgb(168,85,247)",
          borderRadius: "50%",
          filter: "blur(64px)",
          opacity: 0.70,
          transform: `translate(${blobX2}px, ${blobY2}px) scale(${blobS2})`,
        }}
      />
      {/* Album cover */}
      <div
        style={{
          position: "relative", zIndex: 10,
          width: "55%", height: "55%",
          borderRadius: "1.2rem",
          overflow: "hidden",
          border: "2px solid rgba(255,255,255,0.3)",
          boxShadow: "0 0 40px rgba(255,90,200,0.6)",
          transform: `scale(${coverScale})`,
        }}
      >
        {coverUrl ? (
          <Img src={coverUrl} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        ) : (
          <div style={{ width: "100%", height: "100%", backgroundColor: "rgba(255,255,255,0.1)" }} />
        )}
        <div style={{ position: "absolute", inset: 0, background: "linear-gradient(to top right, rgba(255,90,200,0.3), transparent)", mixBlendMode: "overlay" }} />
      </div>
    </div>
  );
};

const NeonArt: React.FC<{ t: number; coverUrl: string | null }> = ({ t, coverUrl }) => {
  const spinAngle = rotAngle(t, 15);
  const discAngle = rotAngle(t, 5);

  return (
    <div style={{ position: "relative", width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
      {/* Conic gradient spinner */}
      <div
        style={{
          position: "absolute",
          width: "95%", height: "95%",
          borderRadius: "50%",
          opacity: 0.40,
          background: "conic-gradient(from 0deg, transparent, #00DCFF 20deg, transparent 40deg)",
          transform: `rotate(${spinAngle}deg)`,
        }}
      />
      {/* Vinyl disc */}
      <div
        style={{
          position: "relative",
          width: "85%", height: "85%",
          borderRadius: "50%",
          backgroundColor: "rgb(10,10,10)",
          border: "1px solid rgba(0,220,255,0.5)",
          boxShadow: "0 0 50px rgba(0,220,255,0.4)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          overflow: "hidden",
          transform: `rotate(${discAngle}deg)`,
        }}
      >
        {/* Groove rings */}
        {[2, 6, 10, 14].map((inset) => (
          <div
            key={inset}
            style={{
              position: "absolute",
              inset: `${inset}%`,
              borderRadius: "50%",
              border: "1px solid rgba(255,255,255,0.1)",
            }}
          />
        ))}
        {/* Center label */}
        <div
          style={{
            position: "absolute",
            width: "45%", height: "45%",
            borderRadius: "50%",
            overflow: "hidden",
            border: "4px solid black",
            boxShadow: "0 4px 30px rgba(0,0,0,0.8)",
          }}
        >
          {coverUrl ? (
            <Img src={coverUrl} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
          ) : (
            <div style={{ width: "100%", height: "100%", backgroundColor: "rgba(255,255,255,0.1)" }} />
          )}
        </div>
        {/* Center dot */}
        <div
          style={{
            position: "absolute",
            width: 16, height: 16,
            borderRadius: "50%",
            backgroundColor: "black",
            border: "1px solid rgba(0,220,255,0.6)",
            boxShadow: "0 0 15px rgba(0,220,255,1)",
            zIndex: 10,
          }}
        />
      </div>
    </div>
  );
};

const InfernoArt: React.FC<{ t: number; coverUrl: string | null }> = ({ t, coverUrl }) => {
  const bobY = -10 * Math.sin((2 * Math.PI * t) / 2);
  const shadowAlpha = 0.1 + 0.3 * Math.abs(Math.sin((2 * Math.PI * t) / 2));

  return (
    <div style={{ position: "relative", width: "100%", height: "100%", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
      {/* Flames inside art area */}
      <div style={{ position: "absolute", inset: 0, overflow: "hidden", borderRadius: "2rem" }}>
        <Flames t={t} />
      </div>
      {/* Floating square album */}
      <div
        style={{
          position: "relative", zIndex: 10,
          width: "70%", aspectRatio: "1",
          backgroundColor: "black",
          border: "1px solid rgba(255,255,255,0.3)",
          padding: 4,
          boxShadow: `0 ${10 + 10 * Math.abs(Math.sin((2 * Math.PI * t) / 2))}px ${40 + 20 * Math.abs(Math.sin((2 * Math.PI * t) / 2))}px rgba(255,255,255,${shadowAlpha})`,
          transform: `translateY(${bobY}px)`,
        }}
      >
        <div style={{ width: "100%", height: "100%", position: "relative", overflow: "hidden", filter: "grayscale(1) contrast(1.25)" }}>
          {coverUrl ? (
            <Img
              src={coverUrl}
              style={{ width: "100%", height: "100%", objectFit: "cover", opacity: 0.9, mixBlendMode: "screen" }}
            />
          ) : (
            <div style={{ width: "100%", height: "100%", backgroundColor: "rgba(255,255,255,0.1)" }} />
          )}
          <div style={{ position: "absolute", inset: 0, background: "linear-gradient(to top, black, transparent, transparent)", opacity: 0.8 }} />
        </div>
      </div>
    </div>
  );
};

/* ── Zigzag Waveform ──────────────────────────────────────────────────────── */

const zigzagPath = "M 0 15 " +
  Array.from({ length: 80 })
    .map((_, i) => {
      const x = ((i + 1) / 80) * 1000;
      const y = i % 2 === 0 ? 5 : 25;
      return `L ${x.toFixed(1)} ${y}`;
    })
    .join(" ");

const ZigzagWaveform: React.FC<{ progress: number; accent: string }> = ({ progress, accent }) => (
  <div style={{ position: "absolute", top: "58.8%", left: "13%", width: "74%", height: 30, marginTop: -15, zIndex: 10 }}>
    <svg viewBox="0 0 1000 30" style={{ width: "100%", height: "100%", filter: "drop-shadow(0 2px 8px rgba(0,0,0,0.5))" }} preserveAspectRatio="none">
      <defs>
        <clipPath id="zigzag-progress">
          <rect x="0" y="0" height="30" width={`${Math.min(100, Math.max(0, progress * 100))}%`} />
        </clipPath>
      </defs>
      {/* Background dimmed zigzag */}
      <path
        d={zigzagPath}
        fill="none"
        stroke="rgba(255,255,255,0.15)"
        strokeWidth="4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* Foreground colored zigzag */}
      <path
        d={zigzagPath}
        fill="none"
        stroke={accent}
        strokeWidth="4"
        strokeLinecap="round"
        strokeLinejoin="round"
        clipPath="url(#zigzag-progress)"
        style={{ filter: `drop-shadow(0 0 6px ${accent})` }}
      />
    </svg>
  </div>
);

/* ── Karaoke Lyrics ───────────────────────────────────────────────────────── */

const KaraokeLyrics: React.FC<{
  words: AudioWord[];
  tAbs: number;
  accent: string;
  textGlow: string;
}> = ({ words, tAbs, accent, textGlow }) => {
  const GROUP_SZ = 5;

  const groups = useMemo(() => {
    const g: AudioWord[][] = [];
    for (let i = 0; i < words.length; i += GROUP_SZ) g.push(words.slice(i, i + GROUP_SZ));
    return g;
  }, [words]);

  // Find current word index
  let wi = -1;
  for (let i = 0; i < words.length; i++) {
    if (words[i].start_s <= tAbs) wi = i;
    else break;
  }

  const gi = wi >= 0 ? Math.floor(wi / GROUP_SZ) : 0;
  const grp = groups[gi] ?? [];
  const li = wi >= 0 ? wi - gi * GROUP_SZ : -1;

  if (grp.length === 0) return null;

  return (
    <div
      style={{
        position: "absolute",
        top: "70.3%",
        bottom: "5%",
        left: "8%",
        right: "8%",
        zIndex: 10,
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "center",
        overflow: "hidden",
      }}
    >
      <div style={{ textAlign: "center", width: "100%" }}>
        <p
          style={{
            fontSize: 58,
            fontWeight: 800,
            letterSpacing: "-0.025em",
            lineHeight: 1.3,
            display: "flex",
            flexWrap: "wrap",
            justifyContent: "center",
            gap: "0 8px",
            fontFamily: "-apple-system, 'Segoe UI', sans-serif",
          }}
        >
          {grp.map((w, idx) => {
            const isHighlighted = idx === li;
            const isPassed = idx < li;

            return (
              <span
                key={idx}
                style={{
                  display: "inline-block",
                  color: isHighlighted
                    ? accent
                    : isPassed
                    ? "rgba(255,255,255,0.4)"
                    : "rgba(255,255,255,0.88)",
                  textShadow: isHighlighted
                    ? textGlow
                    : isPassed
                    ? "none"
                    : "0 4px 10px rgba(0,0,0,0.8)",
                  transform: isHighlighted ? "scale(1.05)" : "scale(1)",
                }}
              >
                {w.word}
              </span>
            );
          })}
        </p>
      </div>
    </div>
  );
};

/* ── Main Composition ─────────────────────────────────────────────────────── */

export const AudioVideoComposition: React.FC<CompositionProps> = ({
  themeId,
  accentColor,
  textGlow,
  bgImageUrl,
  coverImageUrl,
  audioUrl,
  words,
  clipStartS,
  clipDuration,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps; // current time in seconds
  const tAbs = t + clipStartS; // absolute time in full track
  const progress = clipDuration > 0 ? t / clipDuration : 0;
  const dark = THEME_DARK[themeId] ?? THEME_DARK.minimal;

  return (
    <AbsoluteFill style={{ backgroundColor: "black" }}>
      {/* Audio */}
      {audioUrl && <Audio src={audioUrl} />}

      {/* 1. Background — blurred image */}
      <AbsoluteFill>
        {bgImageUrl ? (
          <div style={{ position: "absolute", inset: 0 }}>
            <Img
              src={bgImageUrl}
              style={{
                width: "100%",
                height: "100%",
                objectFit: "cover",
                filter: "blur(32px)",
                transform: "scale(1.1)", // prevent blur edge artifacts
                opacity: themeId === "inferno" ? 0.55 : 0.80,
              }}
            />
            {themeId === "inferno" && (
              <div style={{ position: "absolute", inset: 0, backgroundColor: "rgba(0,0,0,0.45)" }} />
            )}
          </div>
        ) : (
          <div style={{ position: "absolute", inset: 0, backgroundColor: dark }} />
        )}
      </AbsoluteFill>

      {/* 2. Gradient overlays */}
      <AbsoluteFill>
        {/* Theme gradient */}
        <div
          style={{
            position: "absolute",
            inset: 0,
            background: `linear-gradient(to bottom, ${dark.replace("rgb", "rgba").replace(")", ",0.88)")}, ${dark.replace("rgb", "rgba").replace(")", ",0.20)")} 44%, ${dark.replace("rgb", "rgba").replace(")", ",0.20)")} 56%, ${dark.replace("rgb", "rgba").replace(")", ",0.90)")})`,
            mixBlendMode: "multiply",
          }}
        />
        {/* Extra dark bands */}
        <div
          style={{
            position: "absolute",
            inset: 0,
            background: "linear-gradient(to bottom, rgba(0,0,0,0.6) 0%, transparent 40%, transparent 60%, rgba(0,0,0,0.8) 100%)",
          }}
        />
      </AbsoluteFill>

      {/* 3. Template colour tints */}
      {themeId === "vivid" && (
        <div
          style={{
            position: "absolute",
            inset: 0,
            background: "radial-gradient(circle at -200px -200px, rgba(255,90,200,0.22) 0%, rgba(255,90,200,0) 700px)",
          }}
        />
      )}
      {themeId === "neon" && (
        <div
          style={{
            position: "absolute",
            inset: 0,
            background: "radial-gradient(circle at 50% 30%, rgba(0,220,255,0.08) 0%, rgba(0,220,255,0) 800px)",
          }}
        />
      )}

      {/* 4. Particles or Flames (behind card) */}
      {themeId === "inferno" ? (
        <Flames t={t} />
      ) : (
        <Particles color={accentColor} t={t} />
      )}

      {/* 5. Card container */}
      <div
        style={{
          position: "absolute",
          top: "6%",
          left: "8%",
          right: "8%",
          height: "46%",
          borderRadius: "2rem",
          display: "flex",
          flexDirection: "column",
          padding: 24,
          zIndex: 10,
          backgroundColor: THEME_CARD_BG[themeId],
          border: `1px solid ${THEME_CARD_BORDER[themeId]}`,
          boxShadow: THEME_CARD_SHADOW[themeId],
          backdropFilter: themeId === "minimal" ? "blur(40px)" : themeId === "vivid" ? "blur(48px)" : themeId === "neon" ? "blur(12px)" : "blur(40px)",
        }}
      >
        {/* 6. Template art */}
        <div style={{ flex: 1, width: "100%", position: "relative" }}>
          {themeId === "minimal" && (
            <MinimalArt t={t} coverUrl={coverImageUrl} accent={accentColor} />
          )}
          {themeId === "vivid" && (
            <VividArt t={t} coverUrl={coverImageUrl} />
          )}
          {themeId === "neon" && (
            <NeonArt t={t} coverUrl={coverImageUrl} />
          )}
          {themeId === "inferno" && (
            <InfernoArt t={t} coverUrl={coverImageUrl} />
          )}
        </div>

        {/* 7. "NOW PLAYING" label */}
        <div
          style={{
            height: 40,
            marginTop: 16,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <span
            style={{
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: "0.3em",
              color: "rgba(255,255,255,0.5)",
              textTransform: "uppercase",
              fontFamily: "-apple-system, 'Segoe UI', sans-serif",
            }}
          >
            Now Playing
          </span>
        </div>
      </div>

      {/* 8. Zigzag waveform */}
      <ZigzagWaveform progress={progress} accent={accentColor} />

      {/* 9. Karaoke lyrics */}
      <KaraokeLyrics
        words={words}
        tAbs={tAbs}
        accent={accentColor}
        textGlow={textGlow}
      />
    </AbsoluteFill>
  );
};
