"use client";

import React, { useEffect, useRef, useState, useCallback, useMemo } from "react";
import { motion, AnimatePresence } from "motion/react";
import {
  getArtists,
  getArtist,
  listAudioTracks,
  uploadAudioTrack,
  getAudioTrack,
  deleteAudioTrack,
  splitAudioTrack,
  getAudioClip,
  generateAudioVideoClip,
  saveAudioClipSettings,
  updateAudioClipLyrics,
  retranscribeAudioTrack,
  assignAudioClip,
  uploadAudioClipAsset,
  uploadAudioClipVideo,
} from "@/lib/api";
import { createCanvasRenderer } from "./canvasRenderer";
import {
  Upload,
  Music2,
  Loader2,
  CheckCircle2,
  AlertCircle,
  ChevronRight,
  ChevronLeft,
  RefreshCw,
  User,
  Clock,
  FileVideo,
  Wand2,
  Trash2,
  Download,
  FolderOpen,
  MonitorPlay,
  ImageIcon,
  Disc,
  Pause,
  Play,
  Save,
} from "lucide-react";

// ─── Types ───────────────────────────────────────────────────────────────────

interface Artist {
  id: number;
  name: string;
  slug: string;
}

interface AudioWord {
  id?: number;
  word: string;
  start_s: number;
  end_s: number;
}

interface AudioVideoState {
  id?: number;
  status: "pending" | "generating" | "done" | "failed";
  video_path?: string;
  error?: string;
  template_id?: string;
  lyrics_mode?: string;
  background_image_path?: string;
  album_cover_path?: string;
}

interface AudioClipData {
  id: number;
  clip_index: number;
  start_s: number;
  end_s: number;
  local_path?: string;
  words: AudioWord[];
  video: AudioVideoState | null;
  lyrics_text?: string | null;
}

interface AudioTrackData {
  id: number;
  title: string;
  duration_s: number;
  transcription_status?: string;
  words: AudioWord[];
  clips: AudioClipData[];
}

interface TrackSummary {
  id: number;
  title: string;
  duration_s: number;
  created_at?: string;
}

interface TapLine { text: string; start_s: number | null; }

// ─── Constants ────────────────────────────────────────────────────────────────

const TEMPLATES = [
  { id: "minimal", label: "Minimal", dot: "#00ff88" },
  { id: "vivid",   label: "Vivid",   dot: "#ff37af" },
  { id: "neon",    label: "Neon",    dot: "#00d2ff" },
  { id: "inferno", label: "Inferno", dot: "#ffffff" },
];

const STEPS = ["Upload", "Configure", "Edit", "Assign"];

// ─── Figma Design: Themes ────────────────────────────────────────────────────

const OVERLAY_THEMES = {
  minimal: {
    id: "minimal",
    name: "Minimal",
    baseBg: "bg-slate-950",
    gradientOverlay: "from-slate-950/90 via-slate-900/30 to-slate-950/95",
    accent: "#00FFAA",
    cardClass:
      "bg-white/5 backdrop-blur-xl border border-white/10 shadow-[0_0_40px_rgba(0,255,170,0.05)]",
    textGlow: "0 0 15px rgba(0,255,170,0.5)",
  },
  vivid: {
    id: "vivid",
    name: "Vivid",
    baseBg: "bg-[#12001a]",
    gradientOverlay: "from-[#1a0024]/90 via-fuchsia-950/40 to-[#12001a]/95",
    accent: "#FF5AC8",
    cardClass:
      "bg-fuchsia-900/20 backdrop-blur-2xl border border-[#FF5AC8]/30 shadow-[0_0_50px_rgba(255,90,200,0.2)]",
    textGlow: "0 0 20px rgba(255,90,200,0.6)",
  },
  neon: {
    id: "neon",
    name: "Neon",
    baseBg: "bg-black",
    gradientOverlay: "from-black via-cyan-950/20 to-black/95",
    accent: "#00DCFF",
    cardClass:
      "bg-black/60 backdrop-blur-md border border-[#00DCFF]/40 shadow-[inset_0_0_20px_rgba(0,220,255,0.1),0_0_40px_rgba(0,220,255,0.3)]",
    textGlow: "0 0 25px rgba(0,220,255,0.8)",
  },
  inferno: {
    id: "inferno",
    name: "Inferno",
    baseBg: "bg-black",
    gradientOverlay: "from-black/90 via-black/30 to-black/95",
    accent: "#FFFFFF",
    cardClass:
      "bg-black/40 backdrop-blur-xl border border-white/20 shadow-[0_0_30px_rgba(255,255,255,0.1)]",
    textGlow: "0 0 20px rgba(255,255,255,0.9)",
  },
} as const;

type ThemeId = keyof typeof OVERLAY_THEMES;

// ─── Figma Design: Zigzag Waveform Path ──────────────────────────────────────

const ZIGZAG_PATH =
  "M 0 15 " +
  Array.from({ length: 80 })
    .map((_, i) => {
      const x = ((i + 1) / 80) * 1000;
      const y = i % 2 === 0 ? 5 : 25;
      return `L ${x.toFixed(1)} ${y}`;
    })
    .join(" ");

// ─── Figma Design: Particles ─────────────────────────────────────────────────

function OverlayParticles({ color, isPlaying }: { color: string; isPlaying: boolean }) {
  return (
    <div className="absolute inset-0 overflow-hidden pointer-events-none mix-blend-screen">
      {[...Array(20)].map((_, i) => (
        <motion.div
          key={i}
          className="absolute rounded-full"
          style={{
            backgroundColor: color,
            width: Math.random() * 4 + 1 + "px",
            height: Math.random() * 4 + 1 + "px",
            left: Math.random() * 100 + "%",
            top: "100%",
          }}
          animate={{
            y: isPlaying ? [0, -800 - Math.random() * 400] : 0,
            opacity: isPlaying ? [0, 0.8, 0] : 0,
            x: isPlaying ? [0, (Math.random() - 0.5) * 100] : 0,
          }}
          transition={{
            duration: Math.random() * 4 + 4,
            repeat: isPlaying ? Infinity : 0,
            delay: Math.random() * 4,
            ease: "linear",
          }}
        />
      ))}
    </div>
  );
}

// ─── Figma Design: Flames ────────────────────────────────────────────────────

function OverlayFlames({ isPlaying }: { isPlaying: boolean }) {
  return (
    <div className="absolute inset-0 overflow-hidden pointer-events-none mix-blend-screen opacity-70">
      {[...Array(15)].map((_, i) => (
        <motion.div
          key={i}
          className="absolute rounded-[100%] bg-white blur-2xl"
          style={{
            width: Math.random() * 60 + 40 + "px",
            height: Math.random() * 100 + 80 + "px",
            left: Math.random() * 80 + 10 + "%",
            bottom: "-10%",
          }}
          animate={{
            y: isPlaying ? [0, -400 - Math.random() * 300] : 0,
            scaleY: isPlaying ? [1, 2.5] : 1,
            scaleX: isPlaying ? [1, 0.5] : 1,
            opacity: isPlaying ? [0, 0.6, 0] : 0,
            x: isPlaying ? [0, (Math.random() - 0.5) * 50] : 0,
          }}
          transition={{
            duration: Math.random() * 2 + 1.5,
            repeat: isPlaying ? Infinity : 0,
            delay: Math.random() * 2,
            ease: "easeIn",
          }}
        />
      ))}
    </div>
  );
}

// ─── Figma Design: Art Components ────────────────────────────────────────────

function MinimalArt({ isPlaying, albumCover, coverRef }: {
  isPlaying: boolean;
  albumCover: string;
  coverRef?: React.RefObject<HTMLDivElement | null>;
}) {
  return (
    <div className="relative w-full h-full flex items-center justify-center">
      <motion.div
        animate={{ rotate: isPlaying ? 360 : 0 }}
        transition={{ duration: 20, repeat: Infinity, ease: "linear" }}
        className="absolute w-[85%] h-[85%] rounded-full border-[0.5px] border-[#00FFAA]/50 border-dashed"
      />
      <motion.div
        animate={{ rotate: isPlaying ? -360 : 0 }}
        transition={{ duration: 15, repeat: Infinity, ease: "linear" }}
        className="absolute w-[65%] h-[65%] rounded-full border border-[#00FFAA]/40"
      />
      <div className="absolute w-[40%] h-[40%] rounded-full bg-[#00FFAA] blur-3xl opacity-20" />
      <motion.div
        ref={coverRef}
        animate={{ scale: isPlaying ? [1, 1.03, 1] : 1 }}
        transition={{ duration: 1.5, repeat: Infinity, ease: "easeInOut" }}
        className="absolute w-[45%] h-[45%] rounded-full overflow-hidden border-2 border-white/20 shadow-[0_0_30px_rgba(0,255,170,0.3)]"
      >
        {albumCover ? (
          <img src={albumCover} alt="Album Cover" className="w-full h-full object-cover" />
        ) : (
          <div className="w-full h-full bg-white/10 flex items-center justify-center">
            <Disc className="w-1/2 h-1/2 text-white/20" />
          </div>
        )}
      </motion.div>
    </div>
  );
}

function VividArt({ isPlaying, albumCover }: { isPlaying: boolean; albumCover: string }) {
  return (
    <div className="relative w-full h-full rounded-[1.5rem] overflow-hidden bg-fuchsia-950/40 border border-white/10 flex items-center justify-center shadow-inner">
      <motion.div
        animate={{
          x: isPlaying ? [0, 60, -60, 0] : 0,
          y: isPlaying ? [0, -80, 60, 0] : 0,
          scale: isPlaying ? [1, 1.5, 1] : 1,
        }}
        transition={{ duration: 5, repeat: Infinity, ease: "easeInOut" }}
        className="absolute top-0 left-0 w-48 h-48 bg-[#FF5AC8] rounded-full blur-[4rem] opacity-70"
      />
      <motion.div
        animate={{
          x: isPlaying ? [0, -80, 40, 0] : 0,
          y: isPlaying ? [0, 60, -80, 0] : 0,
          scale: isPlaying ? [1, 1.2, 1] : 1,
        }}
        transition={{ duration: 4, repeat: Infinity, ease: "easeInOut" }}
        className="absolute bottom-0 right-0 w-56 h-56 bg-purple-500 rounded-full blur-[4rem] opacity-70"
      />
      <motion.div
        animate={{ scale: isPlaying ? [1, 1.15, 1] : 1 }}
        transition={{ duration: 0.6, repeat: Infinity, ease: "easeInOut" }}
        className="relative z-10 w-[55%] h-[55%] rounded-[1.2rem] overflow-hidden border-2 border-white/30 shadow-[0_0_40px_rgba(255,90,200,0.6)]"
      >
        {albumCover ? (
          <img src={albumCover} alt="Album Cover" className="w-full h-full object-cover" />
        ) : (
          <div className="w-full h-full bg-white/10 flex items-center justify-center">
            <Disc className="w-1/2 h-1/2 text-white/20" />
          </div>
        )}
        <div className="absolute inset-0 bg-gradient-to-tr from-[#FF5AC8]/30 to-transparent mix-blend-overlay" />
      </motion.div>
    </div>
  );
}

function NeonArt({ isPlaying, albumCover, coverRef }: {
  isPlaying: boolean;
  albumCover: string;
  coverRef?: React.RefObject<HTMLDivElement | null>;
}) {
  return (
    <div className="relative w-full h-full flex items-center justify-center">
      <motion.div
        animate={{ rotate: isPlaying ? 360 : 0 }}
        transition={{ duration: 15, repeat: Infinity, ease: "linear" }}
        className="absolute w-[95%] h-[95%] rounded-full opacity-40"
        style={{
          background: "conic-gradient(from 0deg, transparent, #00DCFF 20deg, transparent 40deg)",
        }}
      />
      <motion.div
        ref={coverRef}
        animate={{ rotate: isPlaying ? 360 : 0 }}
        transition={{ duration: 5, repeat: Infinity, ease: "linear" }}
        className="relative w-[85%] h-[85%] rounded-full bg-neutral-950 border border-[#00DCFF]/50 shadow-[0_0_50px_rgba(0,220,255,0.4)] flex items-center justify-center overflow-hidden"
      >
        <div className="absolute inset-2 rounded-full border border-white/10" />
        <div className="absolute inset-6 rounded-full border border-white/10" />
        <div className="absolute inset-10 rounded-full border border-white/10" />
        <div className="absolute inset-14 rounded-full border border-white/10" />
        <div className="absolute w-[45%] h-[45%] rounded-full overflow-hidden border-4 border-black shadow-2xl">
          {albumCover ? (
            <img src={albumCover} alt="Album Label" className="w-full h-full object-cover" />
          ) : (
            <div className="w-full h-full bg-white/10 flex items-center justify-center">
              <Disc className="w-1/2 h-1/2 text-white/20" />
            </div>
          )}
        </div>
        <div className="absolute w-4 h-4 rounded-full bg-black border border-[#00DCFF]/60 shadow-[0_0_15px_rgba(0,220,255,1)] z-10" />
      </motion.div>
    </div>
  );
}

function InfernoArt({ isPlaying, albumCover }: { isPlaying: boolean; albumCover: string }) {
  return (
    <div className="relative w-full h-full flex flex-col items-center justify-center">
      <div className="absolute inset-0 overflow-hidden rounded-[2rem]">
        <OverlayFlames isPlaying={isPlaying} />
      </div>
      <motion.div
        initial={{ boxShadow: "0 10px 40px rgba(255,255,255,0.1)" }}
        animate={{
          y: isPlaying ? [0, -10, 0] : 0,
          boxShadow: isPlaying
            ? [
                "0 10px 40px rgba(255,255,255,0.1)",
                "0 20px 60px rgba(255,255,255,0.4)",
                "0 10px 40px rgba(255,255,255,0.1)",
              ]
            : "0 10px 40px rgba(255,255,255,0.1)",
        }}
        transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
        className="relative z-10 w-[70%] aspect-square bg-black border border-white/30 p-1"
      >
        <div className="w-full h-full relative overflow-hidden grayscale contrast-125">
          {albumCover ? (
            <img
              src={albumCover}
              alt="Album Cover"
              className="w-full h-full object-cover opacity-90 mix-blend-screen"
            />
          ) : (
            <div className="w-full h-full bg-white/10 flex items-center justify-center">
              <Disc className="w-1/2 h-1/2 text-white/20" />
            </div>
          )}
          <div className="absolute inset-0 bg-gradient-to-t from-black via-transparent to-transparent opacity-80" />
        </div>
      </motion.div>
    </div>
  );
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatTime(s: number): string {
  const m = Math.floor(s / 60);
  const sec = (s % 60).toFixed(1).padStart(4, "0");
  return `${m}:${sec}`;
}

function formatDuration(s: number): string {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${sec.toString().padStart(2, "0")}`;
}

/** Resolve a backend file path to a public URL */
function fileUrl(path: string): string {
  return `/api/files/${path}`;
}

// ─── Confirm Modal ────────────────────────────────────────────────────────────

function ConfirmModal({
  title,
  message,
  confirmLabel = "Delete",
  onConfirm,
  onCancel,
}: {
  title: string;
  message: string;
  confirmLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onCancel} />
      {/* Panel */}
      <div className="relative w-full max-w-sm rounded-2xl border border-border bg-card p-6 shadow-2xl">
        <div className="mb-1 flex items-center gap-2">
          <Trash2 className="h-4 w-4 text-destructive" />
          <h3 className="text-base font-semibold">{title}</h3>
        </div>
        <p className="mb-6 text-sm text-muted-foreground">{message}</p>
        <div className="flex justify-end gap-3">
          <button
            onClick={onCancel}
            className="rounded-lg border border-border px-4 py-2 text-sm hover:bg-muted transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className="rounded-lg bg-destructive px-4 py-2 text-sm font-medium text-white hover:bg-destructive/90 transition-colors"
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── PreviewContent ───────────────────────────────────────────────────────────

// ─── Apple Music–style scroll lyrics ─────────────────────────────────────────
function ScrollLyricsView({
  lyricLines,
  overlayLineIndex,
}: {
  lyricLines: string[][];
  overlayLineIndex: number;
  overlayWordIndex: number;
  isPlaying: boolean;
  theme: (typeof OVERLAY_THEMES)[ThemeId];
}) {
  const scrollRef = React.useRef<HTMLDivElement>(null);
  const activeRef = React.useRef<HTMLDivElement>(null);

  // Scroll active line to the vertical center of the container
  React.useEffect(() => {
    const container = scrollRef.current;
    const active    = activeRef.current;
    if (!container || !active) return;
    const mid = container.clientHeight / 2;
    const top = active.offsetTop - mid + active.clientHeight / 2;
    container.scrollTo({ top, behavior: "smooth" });
  }, [overlayLineIndex]);

  return (
    // Outer wrapper: constrained to bottom zone only, clips everything outside
    <div
      className="absolute left-0 right-0 z-10 overflow-hidden pointer-events-none"
      style={{
        top: "63%",
        bottom: "7%",
        // CSS mask fades lines out near the top and bottom edges
        WebkitMaskImage:
          "linear-gradient(to bottom, transparent 0%, black 22%, black 78%, transparent 100%)",
        maskImage:
          "linear-gradient(to bottom, transparent 0%, black 22%, black 78%, transparent 100%)",
      }}
    >
      {/* Scrollable inner — must be overflow-y:scroll (not hidden) for scrollTo() to work */}
      <div ref={scrollRef} className="w-full h-full [&::-webkit-scrollbar]:hidden" style={{ overflowY: "scroll", scrollbarWidth: "none" }}>
        {/* Top spacer so first line can reach the center */}
        <div style={{ height: "50%" }} />

        {lyricLines.map((line, li) => {
          const isActive = li === overlayLineIndex;
          const isPast   = li < overlayLineIndex;

          return (
            <div
              key={li}
              ref={isActive ? activeRef : undefined}
              className="px-7 text-center"
              style={{
                paddingTop:    "0.3rem",
                paddingBottom: "0.3rem",
                transition: "all 0.3s ease",
              }}
            >
              <p
                style={{
                  fontSize:      isActive ? "1.55rem" : "1.1rem",
                  fontWeight:    isActive ? 800 : 500,
                  lineHeight:    1.3,
                  letterSpacing: "-0.01em",
                  color:         isActive ? "#ffffff" : isPast ? "rgba(255,255,255,0.3)" : "rgba(255,255,255,0.2)",
                  textShadow:    isActive ? "0 2px 14px rgba(0,0,0,0.6)" : "none",
                  transition:    "font-size 0.25s ease, color 0.25s ease, font-weight 0.25s ease",
                }}
              >
                {line.join(" ")}
              </p>
            </div>
          );
        })}

        {/* Bottom spacer so last line can reach the center */}
        <div style={{ height: "50%" }} />
      </div>
    </div>
  );
}

interface PreviewContentProps {
  themeId: ThemeId;
  theme: (typeof OVERLAY_THEMES)[ThemeId];
  bgImageUrl: string | null;
  coverImageUrl: string | null;
  lyricLines: string[][];
  isPlaying: boolean;
  overlayLineIndex: number;
  overlayWordIndex: number;
  lyricsMode?: string;
  coverArtRef?: React.RefObject<HTMLDivElement | null>;
  zigzagLayerRef?: React.RefObject<HTMLDivElement | null>;
  lyricsLayerRef?: React.RefObject<HTMLDivElement | null>;
  isGenerating?: boolean;
}

function PreviewContent({
  themeId,
  theme,
  bgImageUrl,
  coverImageUrl,
  lyricLines,
  isPlaying,
  overlayLineIndex,
  overlayWordIndex,
  lyricsMode = "karaoke",
  coverArtRef,
  zigzagLayerRef,
  lyricsLayerRef,
  isGenerating,
}: PreviewContentProps) {
  const zigzagClipId = React.useId();
  const albumCover = coverImageUrl ?? "";
  const isScrollMode = lyricsMode === "scroll";

  return (
    <>
      {/* Background / Environment Layer */}
      <div className="absolute inset-0 z-0 bg-black">
        {bgImageUrl ? (
          <img
            src={bgImageUrl}
            alt="Background"
            className={`absolute inset-0 w-full h-full object-cover transition-all duration-700 ${
              themeId === "inferno" ? "grayscale opacity-60" : "opacity-80"
            }`}
          />
        ) : (
          <div className={`absolute inset-0 ${theme.baseBg}`} />
        )}
        {/* Gradient overlay */}
        <div className={`absolute inset-0 bg-gradient-to-b ${theme.gradientOverlay} transition-colors duration-1000 mix-blend-multiply`} />
        <div className="absolute inset-0 bg-gradient-to-b from-black/60 via-transparent to-black/80" />

        {/* Particles / Flames */}
        {themeId === "inferno" ? (
          <OverlayFlames isPlaying={isPlaying} />
        ) : (
          <OverlayParticles color={theme.accent} isPlaying={isPlaying} />
        )}
      </div>

      {/* 1. ALBUM ART & CARD — top-[6%] to h-[46%] */}
      <div className={`absolute top-[6%] left-[8%] right-[8%] h-[46%] rounded-[2rem] flex flex-col p-6 z-10 transition-all duration-700 ${theme.cardClass}`}>
        {/* Art Container */}
        <div className="flex-1 w-full relative">
          <AnimatePresence mode="wait">
            <motion.div
              key={themeId}
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 1.05 }}
              transition={{ duration: 0.4 }}
              className="absolute inset-0"
            >
              {themeId === "minimal" && <MinimalArt isPlaying={isPlaying} albumCover={albumCover} coverRef={coverArtRef} />}
              {themeId === "vivid" && <VividArt isPlaying={isPlaying} albumCover={albumCover} />}
              {themeId === "neon" && <NeonArt isPlaying={isPlaying} albumCover={albumCover} coverRef={coverArtRef} />}
              {themeId === "inferno" && <InfernoArt isPlaying={isPlaying} albumCover={albumCover} />}
            </motion.div>
          </AnimatePresence>
        </div>

        {/* "NOW PLAYING" Label */}
        <div className="h-10 mt-4 flex items-center justify-center">
          <span className="text-[10px] font-bold tracking-[0.3em] text-white/50 uppercase">
            Now Playing
          </span>
        </div>
      </div>

      {/* 2. PROGRESS BAR — zigzag waveform at top-[58.8%] */}
      <div ref={zigzagLayerRef} className="absolute top-[58.8%] left-[13%] w-[74%] h-[30px] -mt-[15px] z-10">
        <svg viewBox="0 0 1000 30" className="w-full h-full drop-shadow-lg" preserveAspectRatio="none">
          <defs>
            <clipPath id={`zigzag-clip-${zigzagClipId}`}>
              <motion.rect
                x="0" y="0" height="30"
                initial={{ width: "0%" }}
                animate={{ width: isPlaying ? "100%" : "0%" }}
                transition={{
                  duration: lyricLines.length * 2.5 || 10,
                  repeat: isPlaying ? Infinity : 0,
                  ease: "linear",
                }}
              />
            </clipPath>
          </defs>
          {/* Background dimmed zigzag */}
          <path
            d={ZIGZAG_PATH}
            fill="none"
            stroke="rgba(255,255,255,0.15)"
            strokeWidth="4"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          {/* Foreground colored zigzag */}
          <path
            d={ZIGZAG_PATH}
            fill="none"
            stroke={theme.accent}
            strokeWidth="4"
            strokeLinecap="round"
            strokeLinejoin="round"
            clipPath={`url(#zigzag-clip-${zigzagClipId})`}
            style={{ filter: `drop-shadow(0 0 6px ${theme.accent})` }}
          />
        </svg>
      </div>

      {/* 3. LYRICS — karaoke (bottom strip) or Apple Music scroll (full overlay) */}
      {isScrollMode ? (
        <ScrollLyricsView
          lyricLines={lyricLines}
          overlayLineIndex={overlayLineIndex}
          overlayWordIndex={overlayWordIndex}
          isPlaying={isPlaying}
          theme={theme}
        />
      ) : (
        <div ref={lyricsLayerRef} className="absolute top-[70.3%] bottom-[5%] left-[8%] right-[8%] z-10 flex items-start justify-center overflow-hidden">
          <AnimatePresence mode="sync">
            {lyricLines.length > 0 && lyricLines[overlayLineIndex % lyricLines.length] && (
              <motion.div
                key={overlayLineIndex % lyricLines.length}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                transition={{ duration: 0.1, ease: "easeOut" }}
                className="text-center w-full"
              >
                <p className="text-3xl font-extrabold tracking-tight leading-[1.3] drop-shadow-xl flex flex-wrap justify-center gap-x-2 gap-y-1">
                  {lyricLines[overlayLineIndex % lyricLines.length].map((word: string, wIdx: number) => {
                    const isHighlighted = isPlaying && wIdx === overlayWordIndex;
                    const isPassed = isPlaying && wIdx < overlayWordIndex;
                    return (
                      <span
                        key={wIdx}
                        style={{
                          display: "inline-block",
                          color: isHighlighted ? theme.accent : isPassed ? "#ffffff" : "rgba(255,255,255,0.4)",
                          textShadow: isHighlighted ? theme.textGlow : "0 4px 10px rgba(0,0,0,0.8)",
                          transform: isHighlighted ? "scale(1.05)" : "scale(1)",
                          transition: "color 0.12s ease, text-shadow 0.12s ease, transform 0.12s ease",
                        }}
                      >
                        {word}
                      </span>
                    );
                  })}
                </p>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}

      {/* Generating overlay */}
      {isGenerating && (
        <div className="absolute inset-0 z-20 flex flex-col items-center justify-center bg-black/60 backdrop-blur-sm">
          <Loader2 className="h-10 w-10 animate-spin text-foreground" />
          <p className="mt-3 text-sm text-white/60">Generating video...</p>
        </div>
      )}
    </>
  );
}

// ─── Download helper — works on iOS (opens new tab) and desktop/Android ──────

function triggerDownload(url: string, filename: string) {
  const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  if (isIOS) {
    // iOS Safari blocks programmatic <a download> — open in new tab so user
    // can long-press → Save to Files / Save Video
    window.open(url, "_blank");
  } else {
    const a = document.createElement("a");
    a.style.display = "none";
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }
}

// ─── Main Component ───────────────────────────────────────────────────────────

export default function AudioToVideoPage() {
  const [step, setStep] = useState(0);
  const [artists, setArtists] = useState<Artist[]>([]);
  const [selectedArtistId, setSelectedArtistId] = useState<number | null>(null);
  const [artistDetail, setArtistDetail] = useState<any>(null);

  // Upload state
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [audioTitle, setAudioTitle] = useState("");
  const [clipCount, setClipCount] = useState<1 | 3 | 5>(1);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [track, setTrack] = useState<AudioTrackData | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Track library (past tracks for selected artist)
  const [pastTracks, setPastTracks] = useState<TrackSummary[]>([]);
  const [loadingPastTracks, setLoadingPastTracks] = useState(false);
  const [deletingTrackId, setDeletingTrackId] = useState<number | null>(null);
  const [openingTrackId, setOpeningTrackId] = useState<number | null>(null);

  // Configure / generate state
  const [clipConfigs, setClipConfigs] = useState<Record<number, {
    template_id: string;
    lyrics_mode: string;
    bg_path?: string;
    cover_path?: string;
  }>>({});
  const [generating, setGenerating] = useState<Record<number, boolean>>({});
  const [generationErrors, setGenerationErrors] = useState<Record<number, string>>({});

  // Overlay Studio — per-clip lyrics text (textarea) and cover upload
  const [clipLyricsText, setClipLyricsText] = useState<Record<number, string>>({});
  // key = `${clipId}-bg` or `${clipId}-cover` to track each independently
  const [uploadingAsset, setUploadingAsset] = useState<Record<string, boolean>>({});
  // tracks whether config changed after last generate (dirty = needs regen before export)
  const [clipConfigDirty, setClipConfigDirty] = useState<Record<number, boolean>>({});
  // clip id that should auto-download when its generation completes
  const [autoDownloadClipId, setAutoDownloadClipId] = useState<number | null>(null);

  // Review state — per clip words being edited
  const [clipWords, setClipWords] = useState<Record<number, AudioWord[]>>({});
  const [editingClipId, setEditingClipId] = useState<number | null>(null);
  const [savingLyrics, setSavingLyrics] = useState(false);
  const [activeReviewClip, setActiveReviewClip] = useState(0);
  const [isPreviewPaused, setIsPreviewPaused] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const bgInputRef = useRef<HTMLInputElement>(null);
  const coverInputRef = useRef<HTMLInputElement>(null);
  const audioPreviewRef = useRef<HTMLAudioElement>(null);
  const previewCanvasRef = useRef<HTMLDivElement>(null);
  // Layer-composite capture refs
  const coverArtRef    = useRef<HTMLDivElement>(null);
  const zigzagLayerRef = useRef<HTMLDivElement>(null);
  const lyricsLayerRef = useRef<HTMLDivElement>(null);
  const [isExportRecording, setIsExportRecording] = useState(false);
  const [exportProgress, setExportProgress] = useState(0);
  const exportAbortRef = useRef(false);
  const [exportedBlob, setExportedBlob] = useState<Blob | null>(null);
  const [exportedBlobUrl, setExportedBlobUrl] = useState<string | null>(null);
  const [exportedExt, setExportedExt] = useState("webm");
  const [exportClipIndex, setExportClipIndex] = useState(0);
  const [uploadingExport, setUploadingExport] = useState(false);
  const [convertingMp4, setConvertingMp4] = useState(false);
  const exportClipIdRef = useRef<number | null>(null);
  const exportAudioCtxRef = useRef<AudioContext | null>(null);
  // Persists blob URLs per clip so "View Export" button can reopen the modal
  const [exportedBlobUrlByClip, setExportedBlobUrlByClip] = useState<Record<number, string>>({});
  // WebGL render mode — "match" = screen recording, "upgraded" = bloom + soft particles
  const [renderMode, setRenderMode] = useState<"match" | "upgraded">("match");

  // Screen-recording state / refs
  const [isRecordingModalOpen, setIsRecordingModalOpen] = useState(false);
  const captureTargetRef      = useRef<HTMLDivElement | null>(null);
  const isRecordingActiveRef  = useRef(false);
  const recordingAudioRef     = useRef<HTMLAudioElement | null>(null);
  const pendingExportClipRef  = useRef<AudioClipData | null>(null); // clip staged in preview phase
  const rawVideoRef           = useRef<HTMLVideoElement | null>(null);
  const drawRafRef            = useRef<number>(0);
  // Themed info/error modal for export messages (replaces browser alert())
  const [exportInfoModal, setExportInfoModal] = useState<{ title: string; message: string } | null>(null);

  // Overlay preview karaoke state
  const [overlayLineIndex, setOverlayLineIndex] = useState(0);
  const [overlayWordIndex, setOverlayWordIndex] = useState(-1);
  // Refs to avoid setState when nothing changed (prevents 120 re-renders/sec)
  const lastLineIdxRef = useRef(-1);
  const lastWordIdxRef = useRef(-2);

  // Assign state — a clip can be assigned to multiple variations
  const [assignedClips, setAssignedClips] = useState<Record<number, Array<{ variationId: number; variationName: string }>>>({});
  const [assigning, setAssigning] = useState<Record<number, boolean>>({});
  const [selectedVariations, setSelectedVariations] = useState<Record<number, number[]>>({});

  // Confirm modal state
  const [confirmModal, setConfirmModal] = useState<{
    title: string;
    message: string;
    onConfirm: () => void;
  } | null>(null);

  // Tap-to-sync state
  const [tapSyncMode, setTapSyncMode] = useState(false);
  const [tapSyncLines, setTapSyncLines] = useState<TapLine[]>([]);
  const [tapSyncClipId, setTapSyncClipId] = useState<number | null>(null);

  const activeClip = track?.clips.find((c) => c.id === editingClipId) ?? track?.clips[0] ?? null;

  const showConfirm = (title: string, message: string): Promise<boolean> =>
    new Promise((resolve) => {
      setConfirmModal({
        title,
        message,
        onConfirm: () => { setConfirmModal(null); resolve(true); },
      });
    });

  // Poll interval refs
  const pollRef = useRef<NodeJS.Timeout | null>(null);
  // Transcription progress state
  const [transcriptionStatus, setTranscriptionStatus] = useState<"idle" | "pending" | "processing" | "done" | "failed">("idle");
  const transcriptionPollRef = useRef<NodeJS.Timeout | null>(null);
  const [retranscribing, setRetranscribing] = useState(false);

  // ── Load artists ──────────────────────────────────────────────────────────

  useEffect(() => {
    getArtists().then((data) => {
      setArtists(data);
      if (data.length === 1) setSelectedArtistId(data[0].id);
    });
  }, []);

  useEffect(() => {
    if (!selectedArtistId) return;
    getArtist(selectedArtistId).then(setArtistDetail);
    loadPastTracks(selectedArtistId);
  }, [selectedArtistId]);

  // ── Track library helpers ─────────────────────────────────────────────────

  const loadPastTracks = async (artistId: number) => {
    setLoadingPastTracks(true);
    try {
      const data = await listAudioTracks(artistId);
      setPastTracks(Array.isArray(data) ? data : data.tracks ?? []);
    } catch {
      setPastTracks([]);
    } finally {
      setLoadingPastTracks(false);
    }
  };

  const handleOpenTrack = async (trackId: number) => {
    setOpeningTrackId(trackId);
    try {
      const trackData: AudioTrackData = await getAudioTrack(trackId);
      setTrack(trackData);
      const configs: Record<number, { template_id: string; lyrics_mode: string; bg_path?: string; cover_path?: string }> = {};
      const words: Record<number, AudioWord[]> = {};
      // trackData.clips don't carry per-clip words; distribute from the flat
      // trackData.words array (each word has a clip_index field from the DB).
      for (const clip of trackData.clips) {
        configs[clip.id] = {
          template_id: clip.video?.template_id ?? "minimal",
          lyrics_mode: clip.video?.lyrics_mode ?? "karaoke",
          // Restore saved image paths so regeneration carries them forward
          bg_path: clip.video?.background_image_path ?? undefined,
          cover_path: clip.video?.album_cover_path ?? undefined,
        };
        words[clip.id] = (trackData.words ?? []).filter(
          (w: any) => w.clip_index === clip.clip_index,
        );
      }
      setClipConfigs(configs);
      setClipWords(words);
      // Restore saved lyrics text (preserves user line edits across reloads)
      const savedLyrics: Record<number, string> = {};
      for (const clip of trackData.clips) {
        if (clip.lyrics_text) savedLyrics[clip.id] = clip.lyrics_text;
      }
      if (Object.keys(savedLyrics).length > 0) setClipLyricsText(savedLyrics);
      // Restore "View Last Export" for clips that already have an uploaded video
      const blobUrlMap: Record<number, string> = {};
      for (const clip of trackData.clips) {
        if (clip.video?.status === "done" && clip.video?.video_path) {
          blobUrlMap[clip.id] = fileUrl(clip.video.video_path);
        }
      }
      if (Object.keys(blobUrlMap).length > 0) setExportedBlobUrlByClip(blobUrlMap);
      if (trackData.clips.length > 0) setEditingClipId(trackData.clips[0].id);
      setActiveReviewClip(0);
      // Restore transcription status; start polling if still in progress
      const tStatus = (trackData.transcription_status ?? "done") as any;
      setTranscriptionStatus(tStatus);
      if (tStatus === "pending" || tStatus === "processing") {
        startTranscriptionPoll(trackData.id);
      }
      setStep(1);
    } catch (e: any) {
      setExportInfoModal({ title: "Error", message: e?.response?.data?.detail || "Failed to load track" });
    } finally {
      setOpeningTrackId(null);
    }
  };

  const handleDeleteTrack = async (trackId: number) => {
    const ok = await showConfirm(
      "Delete Track",
      "This will permanently delete the track and all its generated video clips. This cannot be undone.",
    );
    if (!ok) return;
    setDeletingTrackId(trackId);
    try {
      await deleteAudioTrack(trackId);
      setPastTracks((t) => t.filter((x) => x.id !== trackId));
      if (track?.id === trackId) {
        setTrack(null);
        setStep(0);
      }
    } catch (e: any) {
      setExportInfoModal({ title: "Error", message: e?.response?.data?.detail || "Failed to delete track" });
    } finally {
      setDeletingTrackId(null);
    }
  };

  // ── File drag and drop ────────────────────────────────────────────────────

  const handleFileDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const f = e.dataTransfer.files[0];
    if (f) {
      setAudioFile(f);
      if (!audioTitle) setAudioTitle(f.name.replace(/\.[^.]+$/, ""));
    }
  }, [audioTitle]);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) {
      setAudioFile(f);
      if (!audioTitle) setAudioTitle(f.name.replace(/\.[^.]+$/, ""));
    }
  };

  // ── Upload + split ────────────────────────────────────────────────────────

  const handleUploadAndProcess = async () => {
    if (!audioFile || !selectedArtistId) return;
    setUploading(true);
    setUploadError("");
    try {
      const uploadResult = await uploadAudioTrack(selectedArtistId, audioFile, audioTitle || audioFile.name);
      const trackId: number = uploadResult.track_id;
      await splitAudioTrack(trackId, clipCount);
      const trackData = await getAudioTrack(trackId);
      setTrack(trackData);
      const configs: Record<number, { template_id: string; lyrics_mode: string; bg_path?: string; cover_path?: string }> = {};
      const words: Record<number, AudioWord[]> = {};
      // Distribute flat trackData.words to each clip by clip_index
      for (const clip of trackData.clips) {
        configs[clip.id] = {
          template_id: clip.video?.template_id ?? "minimal",
          lyrics_mode: clip.video?.lyrics_mode ?? "karaoke",
          bg_path: clip.video?.background_image_path ?? undefined,
          cover_path: clip.video?.album_cover_path ?? undefined,
        };
        words[clip.id] = (trackData.words ?? []).filter(
          (w: any) => w.clip_index === clip.clip_index,
        );
      }
      setClipConfigs(configs);
      setClipWords(words);
      const blobUrlMap2: Record<number, string> = {};
      for (const clip of trackData.clips) {
        if (clip.video?.status === "done" && clip.video?.video_path) {
          blobUrlMap2[clip.id] = fileUrl(clip.video.video_path);
        }
      }
      if (Object.keys(blobUrlMap2).length > 0) setExportedBlobUrlByClip(blobUrlMap2);
      if (trackData.clips.length > 0) setEditingClipId(trackData.clips[0].id);
      // Refresh past tracks list
      if (selectedArtistId) loadPastTracks(selectedArtistId);
      // Start polling for transcription if it's still in progress
      if (uploadResult.transcription_status === "pending" || uploadResult.transcription_status === "processing") {
        startTranscriptionPoll(trackId);
      } else {
        setTranscriptionStatus("done");
      }
      setStep(1);
    } catch (err: any) {
      setUploadError(err?.response?.data?.detail || err?.message || "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  // ── Generate videos ───────────────────────────────────────────────────────

  const handleGenerateClip = async (clipId: number) => {
    const cfg = clipConfigs[clipId] ?? { template_id: "minimal" };
    setGenerating((g) => ({ ...g, [clipId]: true }));
    setGenerationErrors((e) => ({ ...e, [clipId]: "" }));
    try {
      await generateAudioVideoClip(clipId, cfg.template_id, cfg.lyrics_mode ?? "karaoke", cfg.bg_path, cfg.cover_path);
      startPolling();
    } catch (err: any) {
      setGenerationErrors((e) => ({ ...e, [clipId]: err?.response?.data?.detail || err?.message || "Generation failed" }));
      setGenerating((g) => ({ ...g, [clipId]: false }));
    }
  };

  const handleGenerateAll = async () => {
    if (!track) return;
    for (const clip of track.clips) await handleGenerateClip(clip.id);
  };

  const startPolling = useCallback(() => {
    if (pollRef.current) return;
    pollRef.current = setInterval(async () => {
      if (!track) return;
      let allDone = true;
      const updatedClips = await Promise.all(track.clips.map((c) => getAudioClip(c.id).catch(() => c)));
      for (const c of updatedClips) {
        const status = c.video?.status;
        if (status === "generating" || status === "pending") allDone = false;
        if (status !== "generating") {
          setGenerating((g) => ({ ...g, [c.id]: false }));
          // When generation finishes successfully, clear dirty flag and persist export URL
          if (status === "done") {
            setClipConfigDirty((d) => ({ ...d, [c.id]: false }));
            if (c.video?.video_path) {
              setExportedBlobUrlByClip((prev) => ({ ...prev, [c.id]: fileUrl(c.video!.video_path!) }));
            }
            // Auto-download if this clip was queued for it
            setAutoDownloadClipId((prev) => {
              if (prev === c.id && c.video?.video_path) {
                triggerDownload(fileUrl(c.video.video_path), `clip_${c.clip_index + 1}.mp4`);
                return null;
              }
              return prev;
            });
          }
        }
      }
      setTrack((t) => t ? { ...t, clips: updatedClips.map((c) => ({ ...c, words: c.words ?? [] })) } : t);
      if (allDone && pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    }, 3000);
  }, [track]);

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  // ── Transcription background polling ─────────────────────────────────────

  const startTranscriptionPoll = useCallback((trackId: number) => {
    if (transcriptionPollRef.current) clearInterval(transcriptionPollRef.current);
    setTranscriptionStatus("pending");
    transcriptionPollRef.current = setInterval(async () => {
      try {
        const fresh: AudioTrackData = await getAudioTrack(trackId);
        const status = fresh.transcription_status ?? "done";
        setTranscriptionStatus(status as any);
        if (status === "done" || status === "failed") {
          if (transcriptionPollRef.current) { clearInterval(transcriptionPollRef.current); transcriptionPollRef.current = null; }
          if (status === "done") {
            // Distribute words to clips
            const wordsMap: Record<number, AudioWord[]> = {};
            for (const clip of fresh.clips) {
              wordsMap[clip.id] = (fresh.words ?? []).filter((w: any) => w.clip_index === clip.clip_index);
            }
            setClipWords(wordsMap);
            // Clear ALL stale textarea overrides for this track so activeKaraokeLyrics
            // is re-derived from the fresh Whisper words (fixes mismatch after retranscribe).
            setClipLyricsText((lt) => {
              const updated = { ...lt };
              for (const clip of fresh.clips) delete updated[clip.id];
              return updated;
            });
            // Then restore any previously-saved lyrics_text entries from the server
            const savedLyrics: Record<number, string> = {};
            for (const clip of fresh.clips) {
              if (clip.lyrics_text) savedLyrics[clip.id] = clip.lyrics_text;
            }
            if (Object.keys(savedLyrics).length > 0) {
              setClipLyricsText((lt) => ({ ...lt, ...savedLyrics }));
            }
            setTrack(fresh);
          }
        }
      } catch {
        // ignore transient errors
      }
    }, 3000);
  }, []);

  useEffect(() => () => { if (transcriptionPollRef.current) clearInterval(transcriptionPollRef.current); }, []);

  const handleRetranscribe = async () => {
    if (!track) return;
    setRetranscribing(true);
    try {
      await retranscribeAudioTrack(track.id);
      startTranscriptionPoll(track.id);
    } catch (err: any) {
      setExportInfoModal({ title: "Retranscribe failed", message: err?.response?.data?.detail || err?.message || "Unknown error" });
    } finally {
      setRetranscribing(false);
    }
  };

  // ── Overlay karaoke preview — timeupdate-driven sync ─────────────────────

  // Reset karaoke on clip change; pause audio
  useEffect(() => {
    lastLineIdxRef.current = -1;
    lastWordIdxRef.current = -2;
    setOverlayLineIndex(0);
    setOverlayWordIndex(-1);
    setIsPreviewPaused(true);
    if (audioPreviewRef.current) {
      audioPreviewRef.current.pause();
      audioPreviewRef.current.currentTime = 0;
    }
  }, [activeClip?.id]);

  // Pause audio when leaving step 2
  useEffect(() => {
    if (step !== 2 && audioPreviewRef.current) {
      audioPreviewRef.current.pause();
      setIsPreviewPaused(true);
    }
  }, [step]);

  // ── Lyrics text helpers (defined early — needed by karaoke useMemo) ────────

  const wordsToTextEarly = (words: AudioWord[]): string => {
    if (!words.length) return "";
    const lines: string[] = [];
    for (let i = 0; i < words.length; i += 5) {
      lines.push(words.slice(i, i + 5).map((w) => w.word).join(" "));
    }
    return lines.join("\n");
  };

  // ── Karaoke sync: build word→position map from the active clip's lyrics ───

  // Ref so timeupdate handler always reads fresh clipWords without re-attaching
  const clipWordsRef = useRef(clipWords);
  const activeClipRef = useRef(activeClip);
  useEffect(() => { clipWordsRef.current = clipWords; }, [clipWords]);
  useEffect(() => { activeClipRef.current = activeClip; }, [activeClip]);

  // Derive lyric lines for the active clip (mirrors what the canvas renders)
  const activeKaraokeLyrics = useMemo((): string[][] => {
    if (!activeClip) return [];
    const text = clipLyricsText[activeClip.id] !== undefined
      ? clipLyricsText[activeClip.id]
      : wordsToTextEarly(clipWords[activeClip.id] ?? []);
    return text
      .split("\n")
      .map((line) => line.trim().split(/\s+/).filter(Boolean))
      .filter((line) => line.length > 0);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeClip?.id, clipLyricsText, clipWords]);

  // flat index → { lineIdx, wordIdx }
  // Keyed on clipWords length so the RAF index always stays in-bounds even when
  // the textarea word count diverges from the Whisper word count.
  const wordPositionMap = useMemo(() => {
    const lines       = activeKaraokeLyrics;
    const clipWordCnt = (clipWords[activeClip?.id ?? -1] ?? []).length;
    const flatCount   = lines.reduce((s, l) => s + l.length, 0);

    const map: Array<{ lineIdx: number; wordIdx: number }> = [];

    if (flatCount === 0 || clipWordCnt === 0) return map;

    if (flatCount === clipWordCnt) {
      // Counts match — direct 1-to-1 mapping (normal case)
      lines.forEach((line, li) =>
        line.forEach((_, wi) => map.push({ lineIdx: li, wordIdx: wi }))
      );
    } else {
      // Proportional fallback: distribute clipWord indices across display lines
      for (let i = 0; i < clipWordCnt; i++) {
        const displayIdx = Math.min(
          Math.floor((i * flatCount) / clipWordCnt),
          flatCount - 1,
        );
        let rem = displayIdx;
        let lineIdx = lines.length - 1;
        let wordIdx = Math.max(0, lines[lineIdx].length - 1);
        for (let li = 0; li < lines.length; li++) {
          if (rem < lines[li].length) { lineIdx = li; wordIdx = rem; break; }
          rem -= lines[li].length;
        }
        map.push({ lineIdx, wordIdx });
      }
    }
    return map;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeClip?.id, activeKaraokeLyrics, clipWords]);

  // Ref so handler can read latest map without re-attaching
  const wordPositionMapRef = useRef(wordPositionMap);
  useEffect(() => { wordPositionMapRef.current = wordPositionMap; }, [wordPositionMap]);

  // RAF-based karaoke sync — polls at ~60fps, reads fresh refs each frame
  useEffect(() => {
    let rafId: number;
    let lastLogTime = 0; // throttle debug logs to 1/sec

    const tick = () => {
      const audio = isRecordingActiveRef.current
        ? recordingAudioRef.current
        : audioPreviewRef.current;
      const clip  = activeClipRef.current;

      if (audio && clip && !audio.paused) {
        // Whisper timestamps are absolute from full track start.
        // audio.currentTime is relative to the clip segment (starts at 0).
        const t  = audio.currentTime + (clip.start_s ?? 0);
        const ws = clipWordsRef.current[clip.id] ?? [];

        // ── DEBUG (throttled 1/sec) ──────────────────────────────────────────
        const now = performance.now();
        if (now - lastLogTime > 1000) {
          lastLogTime = now;
          console.log("[karaoke-sync]", {
            clipId: clip.id, clipStart: clip.start_s, audioTime: audio.currentTime,
            t, wsLen: ws.length, mapLen: wordPositionMapRef.current.length,
            paused: audio.paused,
            firstWord: ws[0]?.start_s, lastWord: ws[ws.length-1]?.start_s,
          });
        }
        // ─────────────────────────────────────────────────────────────────────

        if (ws.length > 0) {
          // Binary search — O(log n) instead of O(n) every frame
          let lo = 0, hi = ws.length - 1, idx = -1;
          while (lo <= hi) {
            const mid = (lo + hi) >> 1;
            if (ws[mid].start_s <= t) { idx = mid; lo = mid + 1; }
            else hi = mid - 1;
          }

          if (idx !== -1) {
            const pos = wordPositionMapRef.current[idx];
            if (pos) {
              // Guard: only skip if timestamps are clearly invalid — ALL words
              // sitting at ≈0 while the clip starts well past 0 (bad data, e.g.
              // saved before Whisper finished on a non-first clip).
              // For normal playback with valid Whisper timestamps this is always false.
              const lastWordStart = ws[ws.length - 1]?.start_s ?? 0;
              const clipStart     = clip.start_s ?? 0;
              const likelyInvalid = lastWordStart < 0.1 && clipStart > 1;
              if (!likelyInvalid) {
                // Only setState when value actually changed — prevents 120 re-renders/sec
                if (pos.lineIdx !== lastLineIdxRef.current || pos.wordIdx !== lastWordIdxRef.current) {
                  lastLineIdxRef.current = pos.lineIdx;
                  lastWordIdxRef.current = pos.wordIdx;
                  setOverlayLineIndex(pos.lineIdx);
                  setOverlayWordIndex(pos.wordIdx);
                }
              }
            }
          }
        }

        // Update progress from this same loop (no separate RAF needed)
        if (isRecordingActiveRef.current) {
          const clipDur = clip.end_s != null && clip.start_s != null
            ? clip.end_s - clip.start_s
            : audio.duration || 1;
          const pct = Math.min(99, Math.round((audio.currentTime / clipDur) * 100));
          setExportProgress(pct);
        }
      }

      rafId = requestAnimationFrame(tick);
    };

    rafId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId);
  // Restart RAF loop only when clip changes — refs handle fresh data each frame
  }, [activeClip?.id]);

  // ── Lyrics text helpers ──────────────────────────────────────────────────

  /** Convert words array → multi-line textarea text (5 words per line) */
  const wordsToText = (words: AudioWord[]): string => {
    if (!words.length) return "";
    const lines: string[] = [];
    for (let i = 0; i < words.length; i += 5) {
      lines.push(words.slice(i, i + 5).map((w) => w.word).join(" "));
    }
    return lines.join("\n");
  };

  /** Get lyrics text for a clip, deriving from clipWords if not yet set */
  const getLyricsText = (clipId: number): string => {
    if (clipLyricsText[clipId] !== undefined) return clipLyricsText[clipId];
    return wordsToText(clipWords[clipId] ?? []);
  };

  // ── Lyrics editing ────────────────────────────────────────────────────────

  const handleWordChange = (clipId: number, wordIndex: number, field: keyof AudioWord, value: string | number) => {
    setClipWords((cw) => {
      const updated = [...(cw[clipId] ?? [])];
      updated[wordIndex] = { ...updated[wordIndex], [field]: value };
      return { ...cw, [clipId]: updated };
    });
  };

  /** Save lyrics from textarea: split lines→words, update word text (keeps timestamps).
   *  ONLY updates the word array if Whisper already gave us valid timestamps — otherwise
   *  we just persist the text so zero-timestamp words never pollute the sync. */
  const handleSaveLyricsText = async (clipId: number) => {
    const text     = getLyricsText(clipId);
    const newWords = text.split(/\s+/).filter(Boolean);
    const existing = clipWords[clipId] ?? [];

    // Check if Whisper has provided real timestamps (at least one word with start > 0)
    const hasRealTimestamps = existing.some((w) => w.start_s > 0 || w.end_s > 0);

    if (hasRealTimestamps) {
      const merged: AudioWord[] = newWords.map((word, i) => ({
        ...(existing[i] ?? { start_s: existing[existing.length - 1]?.end_s ?? 0, end_s: 0 }),
        word,
      }));
      setClipWords((cw) => ({ ...cw, [clipId]: merged }));
      setSavingLyrics(true);
      try {
        await updateAudioClipLyrics(clipId, merged, text);
      } catch (err: any) {
        setExportInfoModal({ title: "Error", message: err?.response?.data?.detail || "Failed to save lyrics" });
      } finally {
        setSavingLyrics(false);
      }
    } else {
      // No valid timestamps yet — save text only (don't touch the word array)
      setSavingLyrics(true);
      try {
        await updateAudioClipLyrics(clipId, [], text); // empty → backend preserves existing words
      } catch (err: any) {
        setExportInfoModal({ title: "Error", message: err?.response?.data?.detail || "Failed to save lyrics" });
      } finally {
        setSavingLyrics(false);
      }
    }
  };

  const handleSaveLyrics = async (clipId: number) => {
    const words = clipWords[clipId] ?? [];
    setSavingLyrics(true);
    try {
      await updateAudioClipLyrics(clipId, words, getLyricsText(clipId));
    } catch (err: any) {
      setExportInfoModal({ title: "Error", message: err?.response?.data?.detail || "Failed to save lyrics" });
    } finally {
      setSavingLyrics(false);
    }
  };

  // ── Tap-to-sync helpers ───────────────────────────────────────────────────

  const handleStartTapSync = (clipId: number) => {
    const text = getLyricsText(clipId);
    const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
    if (!lines.length) return;
    setTapSyncLines(lines.map((l) => ({ text: l, start_s: null })));
    setTapSyncClipId(clipId);
    setTapSyncMode(true);
    // Reset & play audio from start
    if (audioPreviewRef.current) {
      audioPreviewRef.current.currentTime = 0;
      audioPreviewRef.current.play().catch(() => {});
      setIsPreviewPaused(false);
    }
  };

  const handleTapLine = (idx: number) => {
    const t = audioPreviewRef.current?.currentTime ?? 0;
    setTapSyncLines((lines) => {
      const updated = [...lines];
      updated[idx] = { ...updated[idx], start_s: t };
      return updated;
    });
  };

  const handleApplyTapSync = async () => {
    if (tapSyncClipId === null) return;
    const clipId = tapSyncClipId;
    const clip = track?.clips.find((c) => c.id === clipId);
    // tap timestamps are clip-relative (audio.currentTime, starts at 0).
    // Whisper timestamps (and what the RAF expects) are absolute (full-track offset).
    // Add clip.start_s so saved words match the RAF formula: t = currentTime + clip.start_s
    const clipAbsStart = clip?.start_s ?? 0;
    const clipDuration = clip ? (clip.end_s - clip.start_s) : 30;

    // Convert timed lines → words with evenly-distributed timestamps within each line
    const allWords: AudioWord[] = [];
    const timedLines = tapSyncLines.filter((l) => l.start_s !== null);
    for (let li = 0; li < timedLines.length; li++) {
      const lineStart = timedLines[li].start_s!; // clip-relative seconds
      const lineEnd = li < timedLines.length - 1 ? (timedLines[li + 1].start_s ?? (lineStart + 3)) : clipDuration;
      const lineDuration = Math.max(0.5, lineEnd - lineStart);
      const lineWords = timedLines[li].text.split(/\s+/).filter(Boolean);
      const wordDur = lineDuration / lineWords.length;
      lineWords.forEach((w, wi) => {
        allWords.push({
          word: w,
          start_s: clipAbsStart + lineStart + wi * wordDur,        // absolute
          end_s:   clipAbsStart + lineStart + (wi + 1) * wordDur - 0.05,
        });
      });
    }

    // Build full text from all tap lines (including un-tapped ones at end)
    const fullText = tapSyncLines.map((l) => l.text).join("\n");

    setClipWords((cw) => ({ ...cw, [clipId]: allWords }));
    setClipLyricsText((lt) => ({ ...lt, [clipId]: fullText }));
    setClipConfigDirty((d) => ({ ...d, [clipId]: true }));
    setTapSyncMode(false);
    setTapSyncClipId(null);
    // Pause audio
    if (audioPreviewRef.current) { audioPreviewRef.current.pause(); setIsPreviewPaused(true); }
    // Save immediately
    setSavingLyrics(true);
    try {
      await updateAudioClipLyrics(clipId, allWords, fullText);
    } catch (err: any) {
      setExportInfoModal({ title: "Error", message: err?.response?.data?.detail || "Failed to save sync" });
    } finally {
      setSavingLyrics(false);
    }
  };

  const handleCancelTapSync = () => {
    setTapSyncMode(false);
    setTapSyncClipId(null);
    if (audioPreviewRef.current) { audioPreviewRef.current.pause(); setIsPreviewPaused(true); }
  };

  /** Save lyrics + template/bg/cover settings to server — no generation triggered */
  const [savingSettings, setSavingSettings] = useState(false);
  const handleSaveSettings = async (clipId: number) => {
    setSavingSettings(true);
    try {
      await handleSaveLyricsText(clipId);
      const cfg = clipConfigs[clipId] ?? { template_id: "minimal" };
      await saveAudioClipSettings(clipId, cfg.template_id, cfg.lyrics_mode ?? "karaoke", cfg.bg_path, cfg.cover_path);
      setClipConfigDirty((d) => ({ ...d, [clipId]: false }));
    } catch (err: any) {
      setExportInfoModal({ title: "Error", message: err?.response?.data?.detail || err?.message || "Failed to save settings" });
    } finally {
      setSavingSettings(false);
    }
  };

  // ── Asset upload (BG / cover image) ──────────────────────────────────────

  const handleAssetUpload = async (
    clipId: number,
    file: File,
    assetType: "bg" | "cover",
  ) => {
    const assetKey = `${clipId}-${assetType}`;
    setUploadingAsset((u) => ({ ...u, [assetKey]: true }));
    try {
      const data = await uploadAudioClipAsset(clipId, file, assetType);
      const configKey = assetType === "cover" ? "cover_path" : "bg_path";
      setClipConfigs((c) => ({
        ...c,
        [clipId]: { ...(c[clipId] ?? { template_id: "minimal" }), [configKey]: data.path },
      }));
      // Mark dirty so Export Frame knows a re-generate is needed
      setClipConfigDirty((d) => ({ ...d, [clipId]: true }));
    } catch (err: any) {
      setExportInfoModal({ title: "Upload failed", message: err?.response?.data?.detail || err.message || "Unknown error" });
    } finally {
      setUploadingAsset((u) => ({ ...u, [assetKey]: false }));
    }
  };

  // ── Assign to variation ───────────────────────────────────────────────────

  const handleAssign = async (clipId: number, variations: Array<{ id: number; name: string }>) => {
    const already = assignedClips[clipId] ?? [];
    const toAssign = variations.filter((v) => !already.some((a) => a.variationId === v.id));
    if (!toAssign.length) return;
    setAssigning((a) => ({ ...a, [clipId]: true }));
    const errors: string[] = [];
    for (const v of toAssign) {
      try {
        await assignAudioClip(clipId, v.id);
        setAssignedClips((ac) => ({
          ...ac,
          [clipId]: [...(ac[clipId] ?? []), { variationId: v.id, variationName: v.name }],
        }));
      } catch (err: any) {
        errors.push(`${v.name}: ${err?.response?.data?.detail || "failed"}`);
      }
    }
    setSelectedVariations((s) => ({ ...s, [clipId]: [] }));
    if (errors.length) {
      setExportInfoModal({ title: "Assignment error", message: errors.join("\n") });
    }
    setAssigning((a) => ({ ...a, [clipId]: false }));
  };

  // ─── Export ───────────────────────────────────────────────────────────────

  // Phase 1 — open the preview modal; user will confirm recording in Phase 2
  const handleStartExport = (clip: AudioClipData) => {
    if (!clip.local_path) return;
    if (renderMode === "upgraded") {
      // Upgraded mode skips the preview modal and goes straight to WebGL recording
      handleBeginRecording(clip);
      return;
    }
    setGenerationErrors((e) => ({ ...e, [clip.id]: "" }));
    pendingExportClipRef.current = clip;
    // Pause any playing preview audio — user will hear fresh audio when recording starts
    if (audioPreviewRef.current) audioPreviewRef.current.pause();
    setIsRecordingModalOpen(true);
  };

  // Deterministic wait for a React ref to be attached — replaces unreliable setTimeout
  async function waitForRef(ref: React.RefObject<HTMLElement | null>, tries = 60): Promise<HTMLElement | null> {
    for (let i = 0; i < tries; i++) {
      if (ref.current) return ref.current;
      await new Promise(r => requestAnimationFrame(r));
    }
    return null;
  }

  // Phase 2 — called by "Start Exporting" button inside the modal (or directly for upgraded mode)
  const handleBeginRecording = async (clip: AudioClipData) => {
    if (!clip.local_path) return;
    // Kill any preview audio that might be playing before we start recording
    if (audioPreviewRef.current) {
      audioPreviewRef.current.pause();
      audioPreviewRef.current.currentTime = 0;
    }
    const clipCfg       = clipConfigs[clip.id] ?? { template_id: "minimal" };
    const themeId2      = (clipCfg.template_id ?? "minimal") as ThemeId;
    const theme2        = OVERLAY_THEMES[themeId2] ?? OVERLAY_THEMES.minimal;
    const bgImageUrl2   = clipCfg.bg_path ? fileUrl(clipCfg.bg_path) : null;
    const coverImageUrl2 = clipCfg.cover_path ? fileUrl(clipCfg.cover_path) : null;
    const words2        = clipWords[clip.id] ?? [];
    const clipDuration  = clip.end_s - clip.start_s;

    setIsExportRecording(true);
    setExportProgress(0);
    exportAbortRef.current = false;
    setGenerationErrors((e) => ({ ...e, [clip.id]: "" }));

    try {
      if (renderMode === "upgraded") {
        // ── Upgraded mode: WebGL canvas.captureStream ──────────────────────
        const renderer = await createCanvasRenderer({
          width: 1080, height: 1920,
          themeId: themeId2, theme: theme2,
          words: words2, bgImageUrl: bgImageUrl2, coverImageUrl: coverImageUrl2,
          clipStartS: clip.start_s,
          clipDuration,
          renderMode,
          layerOverrides: undefined,
        });

        const recAudio = new Audio();
        recAudio.crossOrigin = "anonymous";
        recAudio.src = fileUrl(clip.local_path!);
        await new Promise<void>((res, rej) => {
          recAudio.oncanplay = () => res();
          recAudio.onerror = () => rej(new Error("Audio load failed"));
          recAudio.load();
        });

        const audioCtx = new AudioContext();
        exportAudioCtxRef.current = audioCtx;
        const audioSrc  = audioCtx.createMediaElementSource(recAudio);
        const audioDest = audioCtx.createMediaStreamDestination();
        audioSrc.connect(audioDest);
        audioSrc.connect(audioCtx.destination);

        const videoStream = renderer.canvas.captureStream(60);
        const combined = new MediaStream([
          ...videoStream.getVideoTracks(),
          ...audioDest.stream.getAudioTracks(),
        ]);
        const mimeType = MediaRecorder.isTypeSupported("video/webm;codecs=vp9,opus")
          ? "video/webm;codecs=vp9,opus"
          : MediaRecorder.isTypeSupported("video/webm;codecs=vp8,opus")
          ? "video/webm;codecs=vp8,opus"
          : "video/webm";
        const recorder = new MediaRecorder(combined, { mimeType, videoBitsPerSecond: 40_000_000 });
        const chunks: BlobPart[] = [];
        recorder.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data); };

        recAudio.currentTime = 0;
        await recAudio.play();
        recorder.start(250);

        let rafId = 0;
        const tick = () => {
          if (exportAbortRef.current) { recorder.stop(); recAudio.pause(); return; }
          const t = recAudio.currentTime;
          renderer.renderFrame(t);
          setExportProgress(Math.min(99, Math.round((t / clipDuration) * 100)));
          if (t < clipDuration && !recAudio.ended) {
            rafId = requestAnimationFrame(tick);
          } else {
            recAudio.pause();
            recorder.stop();
          }
        };
        rafId = requestAnimationFrame(tick);

        recorder.onstop = () => {
          cancelAnimationFrame(rafId);
          renderer.destroy();
          audioCtx.close();
          exportAudioCtxRef.current = null;
          const blob = new Blob(chunks, { type: mimeType });
          const url  = URL.createObjectURL(blob);
          setExportedBlobUrl(url);
          setExportedBlob(blob);
          setExportedExt("webm");
          setExportClipIndex(clip.clip_index);
          exportClipIdRef.current = clip.id;
          setExportedBlobUrlByClip((prev) => ({ ...prev, [clip.id]: url }));
          setExportProgress(100);
          setIsExportRecording(false);
        };
        return;
      }

      // ── Match mode: screen recording ───────────────────────────────────────
      // 0. Guard: getDisplayMedia is desktop-only (not available on iOS / Android)
      if (!navigator.mediaDevices?.getDisplayMedia) {
        setIsExportRecording(false);
        setIsRecordingModalOpen(false);
        setGenerationErrors((e) => ({
          ...e,
          [clip.id]: "Export requires a desktop browser (Chrome or Edge). Screen recording is not supported on mobile.",
        }));
        return;
      }

      // 0b. AudioContext created synchronously (preserve user-gesture activation)
      const audioCtx = new AudioContext();
      exportAudioCtxRef.current = audioCtx;

      // 1. getDisplayMedia is the FIRST await — locks in gesture activation
      //    Modal is already open (opened in Phase 1), captureTargetRef is already attached
      const displayStream = await navigator.mediaDevices.getDisplayMedia({
        video: {
          preferCurrentTab: true,
          width:     { ideal: 3840 },
          height:    { ideal: 2160 },
          frameRate: { ideal: 60 },
        } as any,
        audio: false,
      });
      // displayVideoTrack = raw tab capture (kept alive to detect "stop sharing")
      const displayVideoTrack = displayStream.getVideoTracks()[0];

      // 2. Resume AudioContext (activation is fresh after the Share prompt)
      await audioCtx.resume();

      // 3. Wait deterministically for captureTargetRef to be in the DOM
      const el = await waitForRef(captureTargetRef as React.RefObject<HTMLElement | null>);
      if (!el) {
        displayVideoTrack.stop(); audioCtx.close(); exportAudioCtxRef.current = null;
        setIsRecordingModalOpen(false); setIsExportRecording(false);
        setExportInfoModal({ title: "Export Cancelled", message: "Preview wasn't ready. Please try again." });
        return;
      }

      // 4. Surface must be the tab — viewport coords only map correctly for tab capture
      const surface = (displayVideoTrack.getSettings() as any).displaySurface;
      if (surface && surface !== "browser") {
        displayVideoTrack.stop(); audioCtx.close(); exportAudioCtxRef.current = null;
        setIsRecordingModalOpen(false); setIsExportRecording(false);
        setExportInfoModal({ title: "Wrong surface", message: 'Click Start Exporting again and choose "This Tab".' });
        return;
      }

      // 5. Let layout fully settle so getBoundingClientRect is final
      await new Promise<void>(r => requestAnimationFrame(() => requestAnimationFrame(() => r())));

      // 6. Pipe the captured tab into a hidden <video>
      const rawVideo = document.createElement("video");
      rawVideoRef.current = rawVideo;
      rawVideo.srcObject = displayStream;
      rawVideo.muted = true;
      (rawVideo as any).playsInline = true;
      await new Promise<void>(r => { rawVideo.onloadedmetadata = () => r(); });
      await rawVideo.play();
      await new Promise<void>(r => requestAnimationFrame(() => r())); // ensure a frame is decoded

      // 7. Map the element's viewport rect into captured-stream pixels,
      //    auto-detecting whether the stream includes browser chrome.
      const streamW = rawVideo.videoWidth;
      const streamH = rawVideo.videoHeight;
      if (!streamW || !streamH) {
        rawVideo.srcObject = null; displayVideoTrack.stop(); audioCtx.close(); exportAudioCtxRef.current = null;
        setIsRecordingModalOpen(false); setIsExportRecording(false);
        setExportInfoModal({ title: "Export Cancelled", message: "Capture didn't start. Please try again." });
        return;
      }

      const dpr       = window.devicePixelRatio || 1;
      const viewportW = window.innerWidth;
      const viewportH = window.innerHeight;
      const outerW    = window.outerWidth;
      const outerH    = window.outerHeight;

      // Decide which reference dimensions the stream was captured at.
      // Tab capture  → stream ≈ viewport × DPR  (no browser chrome)
      // Window/screen → stream ≈ outer × DPR    (includes chrome: tabs, address bar)
      const errViewport = Math.abs(streamW - viewportW * dpr) + Math.abs(streamH - viewportH * dpr);
      const errOuter    = Math.abs(streamW - outerW    * dpr) + Math.abs(streamH - outerH    * dpr);
      const includesChrome = errOuter < errViewport;

      let scaleX: number, scaleY: number, offsetX: number, offsetY: number;
      if (includesChrome) {
        // Stream origin is top-left of the browser window (includes chrome).
        scaleX  = streamW / outerW;
        scaleY  = streamH / outerH;
        offsetX = (outerW - viewportW) / 2; // usually 0 or scrollbar width
        offsetY = outerH - viewportH;       // address bar + tab strip height
      } else {
        // Tab-only capture: stream origin matches top-left of viewport.
        scaleX  = streamW / viewportW;
        scaleY  = streamH / viewportH;
        offsetX = 0;
        offsetY = 0;
      }

      const rect = el.getBoundingClientRect();
      let srcX = Math.round((offsetX + rect.left)  * scaleX);
      let srcY = Math.round((offsetY + rect.top)   * scaleY);
      let srcW = Math.round(rect.width  * scaleX);
      let srcH = Math.round(rect.height * scaleY);
      // Add a small top buffer to absorb any sub-pixel rounding in the chrome-height
      // measurement — this trims the white border artifact without losing meaningful content.
      const topTrim = includesChrome ? 6 : 2; // physical px
      srcY = Math.min(srcY + topTrim, streamH - srcH);
      srcW -= srcW % 2; srcH -= srcH % 2; // even dims for the encoder
      console.log("[export] canvas crop:", {
        streamW, streamH, dpr, viewportW, viewportH, outerW, outerH,
        includesChrome, offsetX, offsetY, scaleX, scaleY,
        rect: { top: rect.top, left: rect.left, width: rect.width, height: rect.height },
        srcX, srcY, srcW, srcH,
      });

      if (srcW < 10 || srcH < 10) {
        rawVideo.srcObject = null; displayVideoTrack.stop(); audioCtx.close(); exportAudioCtxRef.current = null;
        setIsRecordingModalOpen(false); setIsExportRecording(false);
        setExportInfoModal({ title: "Export Cancelled", message: "Could not measure the preview region." });
        return;
      }

      // 8. Draw ONLY that rect onto an offscreen canvas every frame — this is now the PRIMARY path
      const cropCanvas = document.createElement("canvas");
      cropCanvas.width = srcW; cropCanvas.height = srcH;
      const cropCtx = cropCanvas.getContext("2d", { alpha: false })!;
      const draw = () => {
        cropCtx.drawImage(rawVideo, srcX, srcY, srcW, srcH, 0, 0, srcW, srcH);
        drawRafRef.current = requestAnimationFrame(draw);
      };
      drawRafRef.current = requestAnimationFrame(draw);

      // 9. Record the CANVAS stream — guaranteed to contain only the preview rect
      const recordingVideoTrack = cropCanvas.captureStream(60).getVideoTracks()[0];

      // Load audio fully buffered (same-origin — no crossOrigin needed)
      const recAudio = new Audio();
      recAudio.preload = "auto";
      recAudio.src = fileUrl(clip.local_path!);
      await new Promise<void>((res, rej) => {
        recAudio.oncanplaythrough = () => res();
        recAudio.onerror = () => rej(recAudio.error);
        recAudio.load();
      });
      // Force a decode pass to warm the audio buffer — prevents first-frame stutter
      recAudio.currentTime = 0.001;
      await new Promise<void>(r => setTimeout(r, 50));
      recAudio.currentTime = 0;

      // Wire Web Audio graph
      const audioSrc  = audioCtx.createMediaElementSource(recAudio);
      const audioDest = audioCtx.createMediaStreamDestination();
      audioSrc.connect(audioDest);            // → recording
      audioSrc.connect(audioCtx.destination); // → speakers

      // MediaRecorder — canvas video track + audio
      const combined = new MediaStream([recordingVideoTrack, audioDest.stream.getAudioTracks()[0]]);
      const mimeType = MediaRecorder.isTypeSupported("video/webm;codecs=vp9,opus")
        ? "video/webm;codecs=vp9,opus"
        : "video/webm";
      const rec     = new MediaRecorder(combined, { mimeType, videoBitsPerSecond: 40_000_000 });
      const chunks: BlobPart[] = [];
      rec.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data); };

      // 9. Guards — listen on displayVideoTrack for "user stops sharing"
      let aborted = false;
      const beforeUnload = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
      window.addEventListener("beforeunload", beforeUnload);
      const handleHidden = () => {
        if (document.hidden && rec.state !== "inactive") { aborted = true; rec.stop(); }
      };
      document.addEventListener("visibilitychange", handleHidden);
      displayVideoTrack.addEventListener("ended", () => {
        aborted = true;
        if (rec.state !== "inactive") rec.stop();
      }, { once: true });

      // 10. START RECORDER BEFORE PLAYBACK — no clipped intro
      recordingAudioRef.current    = recAudio;
      isRecordingActiveRef.current = true;
      rec.start();                   // ← capture first
      recAudio.currentTime = 0;
      await recAudio.play();         // ← then play; head of song is fully captured
      recAudio.addEventListener("ended", () => {
        if (rec.state !== "inactive") rec.stop();
      }, { once: true });

      // Progress is now driven by the shared sync RAF loop (isRecordingActiveRef = true)

      // 11. onstop — runs when song ends, tab is hidden, or user stops sharing
      rec.onstop = () => {
        cancelAnimationFrame(drawRafRef.current);
        window.removeEventListener("beforeunload", beforeUnload);
        document.removeEventListener("visibilitychange", handleHidden);
        displayVideoTrack.stop();
        if (rawVideoRef.current) { rawVideoRef.current.srcObject = null; rawVideoRef.current = null; }
        audioCtx.close();
        exportAudioCtxRef.current    = null;
        isRecordingActiveRef.current = false;
        recordingAudioRef.current    = null;
        setIsRecordingModalOpen(false);
        setIsExportRecording(false);
        setExportProgress(100);
        if (aborted) {
          setExportInfoModal({
            title: "Export Cancelled",
            message: "Recording stopped because the tab was hidden or sharing ended. Keep this tab in the foreground while recording.",
          });
          return;
        }
        const blob = new Blob(chunks, { type: mimeType });
        const url  = URL.createObjectURL(blob);
        setExportedBlobUrl(url);
        setExportedBlob(blob);
        setExportedExt("webm");
        setExportClipIndex(clip.clip_index);
        exportClipIdRef.current = clip.id;
        setExportedBlobUrlByClip((prev) => ({ ...prev, [clip.id]: url }));
      };
    } catch (err: any) {
      console.error("Export failed", err);
      setGenerationErrors((e) => ({ ...e, [clip.id]: `Export failed: ${err?.message ?? "unknown"}` }));
      setIsExportRecording(false);
      setIsRecordingModalOpen(false);
      isRecordingActiveRef.current = false;
      recordingAudioRef.current    = null;
    }
  };

  // ─── Render ───────────────────────────────────────────────────────────────

  return (
    <>
    <div className="min-h-screen bg-background text-foreground">

      {/* ── Confirm modal ───────────────────────────────────────────────────── */}
      {confirmModal && (
        <ConfirmModal
          title={confirmModal.title}
          message={confirmModal.message}
          confirmLabel="Delete"
          onConfirm={confirmModal.onConfirm}
          onCancel={() => setConfirmModal(null)}
        />
      )}

      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div className="border-b border-border/40 px-4 py-3 sm:px-6 sm:py-4">
        <div className="flex items-center gap-2">
          <Music2 className="h-5 w-5 shrink-0 text-foreground" />
          <h1 className="text-lg font-bold sm:text-xl">Audio to Video</h1>
        </div>

        {/* Step indicator */}
        <div className="mt-3 flex items-center gap-1 sm:gap-2 overflow-x-auto pb-0.5">
          {STEPS.map((s, i) => (
            <div key={s} className="flex shrink-0 items-center gap-1 sm:gap-2">
              <button
                onClick={() => track && i <= step && setStep(i)}
                className={`flex h-6 w-6 sm:h-7 sm:w-7 items-center justify-center rounded-full text-[11px] font-bold transition-colors ${
                  i === step
                    ? "bg-foreground text-background"
                    : i < step
                    ? "bg-foreground/20 text-foreground cursor-pointer"
                    : "bg-muted text-muted-foreground cursor-default"
                }`}
              >
                {i < step ? <CheckCircle2 className="h-3.5 w-3.5" /> : i + 1}
              </button>
              <span className={`hidden sm:inline text-sm ${i === step ? "font-medium text-foreground" : "text-muted-foreground"}`}>{s}</span>
              {i === step && <span className="sm:hidden text-xs font-medium text-foreground">{s}</span>}
              {i < STEPS.length - 1 && <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />}
            </div>
          ))}
        </div>
      </div>

      {/* ── Content ────────────────────────────────────────────────────────── */}
      <div className={`mx-auto px-4 py-6 sm:px-6 sm:py-8 ${step === 2 ? "max-w-6xl" : "max-w-4xl"}`}>

        {/* ── Step 0: Upload ──────────────────────────────────────────────── */}
        {step === 0 && (
          <div className="space-y-6">

            {/* Artist selector */}
            <div>
              <label className="mb-2 block text-sm font-medium">Select Artist</label>
              <div className="flex flex-wrap gap-2">
                {artists.map((a) => (
                  <button
                    key={a.id}
                    onClick={() => setSelectedArtistId(a.id)}
                    className={`rounded-lg border px-3 py-2 text-sm transition-colors ${
                      selectedArtistId === a.id
                        ? "border-foreground bg-foreground/10 text-foreground"
                        : "border-border bg-card hover:border-foreground/40"
                    }`}
                  >
                    {a.name}
                  </button>
                ))}
              </div>
            </div>

            {/* ── Past Tracks Library ─────────────────────────────────────── */}
            {selectedArtistId && (loadingPastTracks || pastTracks.length > 0) && (
              <div>
                <div className="mb-3 flex items-center justify-between">
                  <h2 className="text-sm font-semibold flex items-center gap-2">
                    <FolderOpen className="h-4 w-4 text-foreground" />
                    Your Tracks
                  </h2>
                  {loadingPastTracks && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
                </div>
                <div className="space-y-2">
                  {pastTracks.map((pt) => (
                    <div
                      key={pt.id}
                      className="flex items-center gap-3 rounded-xl border border-border bg-card px-4 py-3"
                    >
                      <Music2 className="h-4 w-4 shrink-0 text-muted-foreground" />
                      <div className="flex-1 min-w-0">
                        <p className="truncate text-sm font-medium">{pt.title}</p>
                        {pt.duration_s && (
                          <p className="text-xs text-muted-foreground">{formatDuration(pt.duration_s)}</p>
                        )}
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        <button
                          onClick={() => handleOpenTrack(pt.id)}
                          disabled={openingTrackId === pt.id}
                          className="flex items-center gap-1.5 rounded-lg bg-foreground px-3 py-1.5 text-xs font-medium text-background disabled:opacity-50"
                        >
                          {openingTrackId === pt.id
                            ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            : <FolderOpen className="h-3.5 w-3.5" />}
                          Open
                        </button>
                        <button
                          onClick={() => handleDeleteTrack(pt.id)}
                          disabled={deletingTrackId === pt.id}
                          className="flex items-center justify-center rounded-lg border border-border p-1.5 text-muted-foreground hover:border-destructive/50 hover:text-destructive transition-colors disabled:opacity-50"
                        >
                          {deletingTrackId === pt.id
                            ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            : <Trash2 className="h-3.5 w-3.5" />}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
                <div className="mt-4 border-t border-border/40 pt-4">
                  <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Upload New Track</p>
                </div>
              </div>
            )}

            {/* Drop zone */}
            <div
              onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={handleFileDrop}
              onClick={() => fileInputRef.current?.click()}
              className={`cursor-pointer rounded-2xl border-2 border-dashed p-6 sm:p-12 text-center transition-colors ${
                isDragging ? "border-foreground bg-foreground/5"
                : audioFile ? "border-green-500/60 bg-green-500/5"
                : "border-border bg-card hover:border-foreground/40"
              }`}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept=".mp3,.wav,.m4a,.aac,.ogg,.flac,audio/*"
                onChange={handleFileSelect}
                className="hidden"
              />
              {audioFile ? (
                <div className="flex flex-col items-center gap-2">
                  <CheckCircle2 className="h-10 w-10 text-green-500" />
                  <p className="text-sm font-medium break-all">{audioFile.name}</p>
                  <p className="text-xs text-muted-foreground">
                    {(audioFile.size / 1024 / 1024).toFixed(2)} MB · tap to change
                  </p>
                </div>
              ) : (
                <div className="flex flex-col items-center gap-3">
                  <div className="relative">
                    <Music2 className="h-12 w-12 text-muted-foreground/40 sm:h-16 sm:w-16" />
                    <Upload className="absolute -bottom-1 -right-1 h-5 w-5 text-foreground sm:h-6 sm:w-6" />
                  </div>
                  <div>
                    <p className="font-medium">Drop audio here or tap to browse</p>
                    <p className="mt-1 text-xs text-muted-foreground">MP3, WAV, M4A, AAC, OGG, FLAC</p>
                  </div>
                </div>
              )}
            </div>

            {/* Track title */}
            <div>
              <label className="mb-2 block text-sm font-medium">Track Title (optional)</label>
              <input
                type="text"
                value={audioTitle}
                onChange={(e) => setAudioTitle(e.target.value)}
                placeholder="e.g. Summer Vibes"
                className="w-full rounded-lg border border-border bg-card px-4 py-2.5 text-sm outline-none focus:border-foreground/60"
              />
            </div>

            {/* Clip count */}
            <div>
              <label className="mb-1 block text-sm font-medium">Number of Clips</label>
              <p className="mb-3 text-xs text-muted-foreground">Audio will be split into equal segments</p>
              <div className="grid grid-cols-3 gap-3">
                {([1, 3, 5] as const).map((n) => (
                  <button
                    key={n}
                    onClick={() => setClipCount(n)}
                    className={`rounded-xl border py-4 text-center transition-colors ${
                      clipCount === n ? "border-foreground bg-foreground/10 text-foreground" : "border-border bg-card hover:border-foreground/40"
                    }`}
                  >
                    <div className="text-2xl font-bold">{n}</div>
                    <div className="text-xs text-muted-foreground">{n === 1 ? "clip" : "clips"}</div>
                  </button>
                ))}
              </div>
            </div>

            {uploadError && (
              <div className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{uploadError}</span>
              </div>
            )}

            <button
              onClick={handleUploadAndProcess}
              disabled={!audioFile || !selectedArtistId || uploading}
              className="w-full rounded-xl bg-foreground py-3 font-semibold text-background transition-opacity disabled:opacity-50"
            >
              {uploading ? (
                <span className="flex items-center justify-center gap-2">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  <span className="text-sm">Uploading…</span>
                </span>
              ) : "Process Audio →"}
            </button>
          </div>
        )}

        {/* ── Step 1: Configure ────────────────────────────────────────────── */}
        {step === 1 && track && (
          <div className="space-y-5">

            {/* Header row */}
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h2 className="text-base font-bold sm:text-lg">{track.title}</h2>
                <p className="text-sm text-muted-foreground">
                  {formatDuration(track.duration_s)} · {track.clips.length} clip{track.clips.length !== 1 ? "s" : ""} · {track.words.length} words
                </p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => handleDeleteTrack(track.id)}
                  disabled={deletingTrackId === track.id}
                  className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm text-muted-foreground hover:border-destructive/50 hover:text-destructive transition-colors"
                >
                  {deletingTrackId === track.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                  <span className="hidden sm:inline">Delete</span>
                </button>
              </div>
            </div>

            {/* Transcription progress banner */}
            {(transcriptionStatus === "pending" || transcriptionStatus === "processing") && (
              <div className="flex items-center gap-3 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-600">
                <Loader2 className="h-4 w-4 shrink-0 animate-spin" />
                <div>
                  <p className="font-medium">Transcribing lyrics in the background…</p>
                  <p className="text-xs text-amber-500/80 mt-0.5">This may take a minute. The page will update automatically when done.</p>
                </div>
              </div>
            )}
            {transcriptionStatus === "failed" && (
              <div className="flex items-center justify-between gap-3 rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
                <div className="flex items-center gap-2">
                  <AlertCircle className="h-4 w-4 shrink-0" />
                  <p>Transcription failed. Words may be missing or incomplete.</p>
                </div>
                <button
                  onClick={handleRetranscribe}
                  disabled={retranscribing}
                  className="shrink-0 flex items-center gap-1 rounded-lg border border-destructive/40 px-3 py-1.5 text-xs font-medium hover:bg-destructive/10 disabled:opacity-40"
                >
                  {retranscribing ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
                  Retry
                </button>
              </div>
            )}

            {track.clips.map((clip) => {
              const cfg = clipConfigs[clip.id] ?? { template_id: "minimal" };
              const videoStatus = clip.video?.status;
              const isGenerating = generating[clip.id] || videoStatus === "generating";

              return (
                <div key={clip.id} className="rounded-2xl border border-border bg-card p-4 sm:p-5">
                  <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                      <p className="font-semibold">Clip {clip.clip_index + 1}</p>
                      <p className="text-xs text-muted-foreground">
                        {formatTime(clip.start_s)} – {formatTime(clip.end_s)} · {clipWords[clip.id]?.length ?? clip.words?.length ?? 0} words
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      {videoStatus === "done" && clip.video?.video_path && (
                        <a
                          href={fileUrl(clip.video.video_path)}
                          download={`clip_${clip.clip_index + 1}.mp4`}
                          className="flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-xs text-muted-foreground hover:border-foreground/40 hover:text-foreground transition-colors"
                        >
                          <Download className="h-3.5 w-3.5" /> Download
                        </a>
                      )}
                      {videoStatus === "done" && <span className="flex items-center gap-1 text-xs text-green-500"><CheckCircle2 className="h-3.5 w-3.5" /> Done</span>}
                      {videoStatus === "failed" && <span className="flex items-center gap-1 text-xs text-destructive"><AlertCircle className="h-3.5 w-3.5" /> Failed</span>}
                    </div>
                  </div>

                  {/* Template selector */}
                  <div>
                    <p className="mb-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">Template</p>
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                      {TEMPLATES.map((t) => (
                        <button
                          key={t.id}
                          onClick={() => setClipConfigs((c) => ({ ...c, [clip.id]: { ...cfg, template_id: t.id } }))}
                          className={`flex items-center gap-3 rounded-xl border p-3 text-left transition-all sm:flex-col sm:items-start sm:gap-0 ${
                            cfg.template_id === t.id ? "border-foreground ring-1 ring-foreground" : "border-border hover:border-foreground/40"
                          }`}
                        >
                          <div>
                            <p className="text-xs font-semibold">{t.label}</p>
                          </div>
                        </button>
                      ))}
                    </div>
                  </div>

                  {generationErrors[clip.id] && (
                    <p className="mt-2 text-xs text-destructive">{generationErrors[clip.id]}</p>
                  )}
                </div>
              );
            })}

            <div className="flex items-center justify-between pt-1">
              <button onClick={() => setStep(0)} className="flex items-center gap-2 rounded-lg border border-border px-4 py-2.5 text-sm">
                <ChevronLeft className="h-4 w-4" /> Back
              </button>
              <button
                onClick={() => { setActiveReviewClip(0); setEditingClipId(track.clips[0]?.id ?? null); setStep(2); }}
                className="flex items-center gap-2 rounded-lg bg-foreground px-4 py-2.5 text-sm font-medium text-background"
              >
                Review & Edit <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}

        {/* ── Step 2: Overlay Studio (Figma Design) ──────────────────────── */}
        {step === 2 && track && (() => {
          const cfg        = clipConfigs[activeClip?.id ?? -1] ?? { template_id: "minimal", lyrics_mode: "karaoke" };
          const lyricsText = activeClip ? getLyricsText(activeClip.id) : "";
          const isGen      = !!(activeClip && (generating[activeClip.id] || activeClip.video?.status === "generating"));
          const themeId    = (cfg.template_id || "minimal") as ThemeId;
          const theme      = OVERLAY_THEMES[themeId] ?? OVERLAY_THEMES.minimal;
          const lyricsMode = cfg.lyrics_mode ?? "karaoke";
          const coverUrl   = cfg.cover_path ? fileUrl(cfg.cover_path) : "";
          const bgUrl      = cfg.bg_path ? fileUrl(cfg.bg_path) : "";

          // Use the pre-computed lyric lines (same source as the karaoke sync)
          const lyricLines = activeKaraokeLyrics;

          return (
            <div className="space-y-3">

              {/* Clip tabs */}
              <div className="flex gap-1 overflow-x-auto border-b border-border">
                {track.clips.map((clip, i) => (
                  <button
                    key={clip.id}
                    onClick={() => { setActiveReviewClip(i); setEditingClipId(clip.id); }}
                    className={`shrink-0 border-b-2 px-4 py-2.5 text-sm font-medium transition-colors ${
                      activeReviewClip === i
                        ? "border-foreground text-foreground"
                        : "border-transparent text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    Clip {i + 1}
                    {clip.video?.status === "done" && (
                      <span className="ml-1.5 inline-block h-1.5 w-1.5 rounded-full bg-green-400" />
                    )}
                  </button>
                ))}
              </div>

              {activeClip && (
                /* ── Main layout: Settings Panel LEFT · 9:16 Canvas RIGHT ── */
                <div className="flex flex-col gap-6 xl:flex-row xl:items-start xl:justify-center">

                  {/* ══ LEFT: Settings Panel (Overlay Studio) ═══════════════ */}
                  <div className="w-full xl:max-w-lg shrink-0 rounded-2xl border border-border bg-card p-6 space-y-6 shadow-2xl xl:max-h-[900px] overflow-y-auto">

                    {/* Hidden file inputs */}
                    <input ref={bgInputRef} type="file" accept="image/*" className="hidden"
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (f && activeClip) handleAssetUpload(activeClip.id, f, "bg");
                        e.target.value = "";
                      }} />
                    <input ref={coverInputRef} type="file" accept="image/*" className="hidden"
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (f && activeClip) handleAssetUpload(activeClip.id, f, "cover");
                        e.target.value = "";
                      }} />

                    {/* Hidden audio element for preview playback */}
                    {activeClip.local_path && (
                      <audio
                        ref={audioPreviewRef}
                        src={fileUrl(activeClip.local_path)}
                        loop
                        preload="auto"
                        className="hidden"
                      />
                    )}

                    {/* Header */}
                    <div>
                      <div className="flex items-center gap-3 mb-2">
                        <MonitorPlay className="w-6 h-6 text-foreground" />
                        <h1 className="text-2xl font-bold text-foreground">Overlay Studio</h1>
                      </div>
                      <p className="text-muted-foreground text-sm">Configure your cinematic music template.</p>
                    </div>

                    {/* Media Uploads */}
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2 block">Background</label>
                        <button
                          onClick={() => bgInputRef.current?.click()}
                          disabled={uploadingAsset[`${activeClip.id}-bg`]}
                          className="flex flex-col items-center justify-center gap-2 w-full p-4 border-2 border-dashed border-border hover:border-muted-foreground rounded-xl cursor-pointer transition-colors bg-muted/30 group disabled:opacity-50"
                        >
                          {uploadingAsset[`${activeClip.id}-bg`]
                            ? <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
                            : <ImageIcon className="w-5 h-5 text-muted-foreground group-hover:text-foreground" />}
                          <span className="text-xs font-medium text-muted-foreground">
                            {cfg.bg_path ? "✓ BG set" : "Change BG"}
                          </span>
                        </button>
                      </div>
                      <div>
                        <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2 block">Album Cover</label>
                        <button
                          onClick={() => coverInputRef.current?.click()}
                          disabled={uploadingAsset[`${activeClip.id}-cover`]}
                          className="flex flex-col items-center justify-center gap-2 w-full p-4 border-2 border-dashed border-border hover:border-muted-foreground rounded-xl cursor-pointer transition-colors bg-muted/30 group disabled:opacity-50"
                        >
                          {uploadingAsset[`${activeClip.id}-cover`]
                            ? <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
                            : <Disc className="w-5 h-5 text-muted-foreground group-hover:text-foreground" />}
                          <span className="text-xs font-medium text-muted-foreground">
                            {cfg.cover_path ? "✓ Cover set" : "Change Cover"}
                          </span>
                        </button>
                      </div>
                    </div>

                    {/* Lyrics Editor */}
                    <div className="space-y-2">
                      <div className="flex items-center justify-between">
                        <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                          Lyrics Content
                        </label>
                        <div className="flex items-center gap-2">
                          {/* Transcription status badge */}
                          {(transcriptionStatus === "pending" || transcriptionStatus === "processing") && (
                            <span className="flex items-center gap-1 text-[10px] text-amber-500">
                              <Loader2 className="h-3 w-3 animate-spin" /> Transcribing…
                            </span>
                          )}
                          {transcriptionStatus === "failed" && (
                            <span className="text-[10px] text-destructive">Transcription failed</span>
                          )}
                          {/* Retranscribe button */}
                          <button
                            onClick={handleRetranscribe}
                            disabled={retranscribing || transcriptionStatus === "pending" || transcriptionStatus === "processing"}
                            title="Re-run Whisper transcription"
                            className="flex items-center gap-1 rounded-lg border border-border px-2 py-1 text-[10px] text-muted-foreground hover:text-foreground hover:border-foreground/40 transition-colors disabled:opacity-40"
                          >
                            {retranscribing ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
                            Retranscribe
                          </button>
                        </div>
                      </div>

                      {tapSyncMode && tapSyncClipId === activeClip.id ? (
                        /* ── Tap-to-sync panel ── */
                        <div className="rounded-xl border border-border bg-background overflow-hidden">
                          <div className="px-3 py-2 bg-muted/50 border-b border-border flex items-center justify-between">
                            <p className="text-xs font-semibold text-foreground">Tap each line as it plays</p>
                            <div className="flex gap-2">
                              <button
                                onClick={() => {
                                  if (audioPreviewRef.current) {
                                    if (audioPreviewRef.current.paused) { audioPreviewRef.current.play().catch(() => {}); setIsPreviewPaused(false); }
                                    else { audioPreviewRef.current.pause(); setIsPreviewPaused(true); }
                                  }
                                }}
                                className="flex items-center gap-1 rounded-lg bg-muted px-2 py-1 text-[10px] font-medium text-foreground"
                              >
                                {isPreviewPaused ? <Play className="h-3 w-3 fill-current" /> : <Pause className="h-3 w-3 fill-current" />}
                                {isPreviewPaused ? "Play" : "Pause"}
                              </button>
                            </div>
                          </div>
                          <div className="max-h-48 overflow-y-auto divide-y divide-border">
                            {tapSyncLines.map((line, idx) => (
                              <button
                                key={idx}
                                onClick={() => handleTapLine(idx)}
                                className={`w-full flex items-center justify-between px-3 py-2.5 text-left transition-colors ${
                                  line.start_s !== null ? "bg-green-500/10" : "hover:bg-muted/40"
                                }`}
                              >
                                <span className="text-sm text-foreground leading-snug">{line.text}</span>
                                <span className={`ml-2 shrink-0 text-[10px] font-mono ${line.start_s !== null ? "text-green-400" : "text-muted-foreground"}`}>
                                  {line.start_s !== null ? `${line.start_s.toFixed(1)}s` : "tap"}
                                </span>
                              </button>
                            ))}
                          </div>
                          <div className="px-3 py-2 bg-muted/30 border-t border-border flex gap-2">
                            <button
                              onClick={handleApplyTapSync}
                              disabled={savingLyrics || tapSyncLines.every((l) => l.start_s === null)}
                              className="flex-1 flex items-center justify-center gap-1 rounded-lg bg-foreground text-background text-xs font-semibold py-2 disabled:opacity-40"
                            >
                              {savingLyrics ? <Loader2 className="h-3 w-3 animate-spin" /> : <CheckCircle2 className="h-3 w-3" />}
                              Apply Timing
                            </button>
                            <button onClick={handleCancelTapSync} className="rounded-lg border border-border px-3 py-2 text-xs text-muted-foreground hover:text-foreground">
                              Cancel
                            </button>
                          </div>
                        </div>
                      ) : (
                        /* ── Normal textarea ── */
                        <div className="space-y-1.5">
                          <textarea
                            value={lyricsText}
                            onChange={(e) => {
                              setClipLyricsText((lt) => ({ ...lt, [activeClip.id]: e.target.value }));
                              setClipConfigDirty((d) => ({ ...d, [activeClip.id]: true }));
                            }}
                            className="w-full h-32 bg-background border border-border rounded-xl p-3 text-foreground focus:outline-none focus:border-foreground/60/50 resize-none font-medium [&::-webkit-scrollbar]:hidden"
                            style={{ scrollbarWidth: "none", fontSize: "16px" }}
                            placeholder="Enter lyrics here… (one line per lyric line)"
                          />
                          <button
                            onClick={() => handleStartTapSync(activeClip.id)}
                            disabled={!lyricsText.trim() || !activeClip.local_path}
                            className="flex w-full items-center justify-center gap-1.5 rounded-xl border border-border py-2 text-xs text-muted-foreground hover:border-foreground/40 hover:text-foreground transition-colors disabled:opacity-40"
                          >
                            <Clock className="h-3.5 w-3.5" /> Sync Timing (tap each line)
                          </button>
                        </div>
                      )}
                    </div>

                    {/* Variant Selector */}
                    <div>
                      <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3 block">Design Variant</label>
                      <div className="grid grid-cols-2 gap-3">
                        {Object.values(OVERLAY_THEMES).map((t) => (
                          <button
                            key={t.id}
                            onClick={() => {
                              setClipConfigs((c) => ({
                                ...c,
                                [activeClip.id]: { ...cfg, template_id: t.id },
                              }));
                              setClipConfigDirty((d) => ({ ...d, [activeClip.id]: true }));
                            }}
                            className={`py-3 px-3 rounded-xl border-2 transition-all flex items-center justify-start gap-3 ${
                              themeId === t.id
                                ? "border-foreground bg-muted/40"
                                : "border-border bg-background hover:border-muted-foreground"
                            }`}
                          >
                            <span className="text-sm font-semibold truncate">{t.name}</span>
                          </button>
                        ))}
                      </div>
                    </div>

                    {/* Lyrics Mode */}
                    <div>
                      <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3 block">Lyrics Style</label>
                      <div className="grid grid-cols-2 gap-3">
                        {([
                          { id: "karaoke", name: "Karaoke", desc: "One line, word-by-word" },
                          { id: "scroll",  name: "Scroll",  desc: "Apple Music style" },
                        ] as const).map((mode) => (
                          <button
                            key={mode.id}
                            onClick={() => {
                              setClipConfigs((c) => ({
                                ...c,
                                [activeClip.id]: { ...cfg, lyrics_mode: mode.id },
                              }));
                              setClipConfigDirty((d) => ({ ...d, [activeClip.id]: true }));
                            }}
                            className={`py-3 px-3 rounded-xl border-2 transition-all flex flex-col items-start gap-0.5 ${
                              lyricsMode === mode.id
                                ? "border-foreground bg-muted/40"
                                : "border-border bg-background hover:border-muted-foreground"
                            }`}
                          >
                            <span className="text-sm font-semibold">{mode.name}</span>
                            <span className="text-[10px] text-muted-foreground">{mode.desc}</span>
                          </button>
                        ))}
                      </div>
                    </div>

                    {generationErrors[activeClip.id] && (
                      <p className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
                        {generationErrors[activeClip.id]}
                      </p>
                    )}

                    {/* Action Buttons */}
                    <div className="pt-4 border-t border-border space-y-3">

                      {/* Render mode toggle */}
                      <div className="flex gap-2">
                        {(["match", "upgraded"] as const).map((mode) => (
                          <button
                            key={mode}
                            onClick={() => setRenderMode(mode)}
                            className={`flex-1 py-2 text-xs font-semibold rounded-xl border transition-all ${
                              renderMode === mode
                                ? "border-foreground bg-foreground text-background"
                                : "border-border text-muted-foreground hover:border-foreground/40"
                            }`}
                          >
                            {mode === "match" ? "🎯 Match Preview" : "✨ Upgraded (Bloom)"}
                          </button>
                        ))}
                      </div>

                      <div className="grid grid-cols-2 gap-3">
                        <button
                          onClick={() => {
                            const next = !isPreviewPaused;
                            setIsPreviewPaused(!isPreviewPaused);
                            if (audioPreviewRef.current) {
                              if (next) audioPreviewRef.current.pause();
                              else audioPreviewRef.current.play().catch(() => {});
                            }
                          }}
                          className="w-full flex items-center justify-center gap-2 py-3.5 bg-muted text-foreground font-semibold rounded-xl hover:bg-muted/80 transition-colors"
                        >
                          {isPreviewPaused
                            ? <><Play className="w-4 h-4 shrink-0 fill-current" /><span className="truncate">Play</span></>
                            : <><Pause className="w-4 h-4 shrink-0 fill-current" /><span className="truncate">Pause</span></>}
                        </button>

                        {/* Export — screen recording (match) or WebGL (upgraded) */}
                        {isExportRecording ? (
                          <button disabled className="w-full flex items-center justify-center gap-2 py-3.5 bg-foreground/80 text-background font-semibold rounded-xl">
                            <Loader2 className="w-4 h-4 shrink-0 animate-spin" />
                            <span className="truncate">{exportProgress}%</span>
                          </button>
                        ) : (
                          <button
                            onClick={() => { if (activeClip) handleStartExport(activeClip); }}
                            className="w-full flex items-center justify-center gap-2 py-3.5 bg-foreground text-background font-semibold rounded-xl hover:bg-foreground/90 transition-colors"
                          >
                            <Download className="w-4 h-4 shrink-0" /><span className="truncate">Export</span>
                          </button>
                        )}
                      </div>

                      {/* View Last Export — reopen modal */}
                      {exportedBlobUrlByClip[activeClip.id] && !isExportRecording && (
                        <button
                          onClick={() => {
                            setExportedBlobUrl(exportedBlobUrlByClip[activeClip.id]);
                            setExportClipIndex(activeClip.clip_index);
                            exportClipIdRef.current = activeClip.id;
                          }}
                          className="flex w-full items-center justify-center gap-2 rounded-xl border border-border py-2.5 text-sm text-muted-foreground hover:border-foreground/40 hover:text-foreground transition-colors"
                        >
                          <MonitorPlay className="h-3.5 w-3.5" /> View Last Export
                        </button>
                      )}
                    </div>

                    {/* Save Settings */}
                    {clipConfigDirty[activeClip.id] && !savingSettings && (
                      <p className="text-center text-xs text-amber-500 flex items-center justify-center gap-1">
                        <span className="inline-block h-1.5 w-1.5 rounded-full bg-amber-500 animate-pulse" />
                        Unsaved changes — click Save Settings
                      </p>
                    )}
                    <button
                      onClick={() => handleSaveSettings(activeClip.id)}
                      disabled={savingSettings || savingLyrics}
                      className={`flex w-full items-center justify-center gap-2 rounded-xl border py-2.5 text-sm transition-colors disabled:opacity-40 ${
                        clipConfigDirty[activeClip.id]
                          ? "border-amber-500/60 bg-amber-500/10 text-amber-600 hover:bg-amber-500/20 font-medium"
                          : "border-border text-muted-foreground hover:border-foreground/40 hover:text-foreground"
                      }`}
                    >
                      {savingSettings
                        ? <><Loader2 className="h-3.5 w-3.5 animate-spin" /> Saving…</>
                        : clipConfigDirty[activeClip.id]
                        ? <><Save className="h-3.5 w-3.5" /> Save Settings</>
                        : <><CheckCircle2 className="h-3.5 w-3.5" /> Save Settings</>}
                    </button>
                  </div>

                  {/* ══ RIGHT: 9:16 Canvas (Figma Design) ═════════════════════ */}
                  <div className="flex flex-1 items-start justify-center pt-2">
                    <div ref={previewCanvasRef} className="relative w-full max-w-[360px] md:max-w-[420px] aspect-[9/16] bg-black rounded-[2.5rem] overflow-hidden shadow-2xl ring-4 ring-neutral-800 flex-shrink-0 isolate">
                      <PreviewContent
                        themeId={themeId}
                        theme={theme}
                        bgImageUrl={bgUrl || null}
                        coverImageUrl={coverUrl || null}
                        lyricLines={lyricLines}
                        isPlaying={!isPreviewPaused}
                        overlayLineIndex={overlayLineIndex}
                        overlayWordIndex={overlayWordIndex}
                        lyricsMode={lyricsMode}
                        coverArtRef={coverArtRef}
                        zigzagLayerRef={zigzagLayerRef}
                        lyricsLayerRef={lyricsLayerRef}
                        isGenerating={isGen}
                      />
                    </div>

                    {/* Below canvas: timing info */}
                    <div className="hidden" /> {/* spacer for layout */}
                  </div>

                </div>
              )}

              {/* Timing info below main layout */}
              {activeClip && (
                <div className="flex items-center justify-center gap-4 text-xs text-muted-foreground pt-1">
                  <span className="flex items-center gap-1">
                    <Clock className="h-3.5 w-3.5" />
                    {formatTime(activeClip.start_s)} – {formatTime(activeClip.end_s)}
                  </span>
                  <span>{(activeClip.end_s - activeClip.start_s).toFixed(1)}s</span>
                </div>
              )}

              {/* Nav */}
              <div className="flex items-center justify-between pt-2">
                <button
                  onClick={() => setStep(1)}
                  className="flex items-center gap-2 rounded-lg border border-border px-4 py-2.5 text-sm"
                >
                  <ChevronLeft className="h-4 w-4" /> Back
                </button>
                <button
                  onClick={() => setStep(3)}
                  className="flex items-center gap-2 rounded-lg bg-foreground px-4 py-2.5 text-sm font-medium text-background"
                >
                  Assign <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            </div>
          );
        })()}

        {/* ── Step 3: Assign ───────────────────────────────────────────────── */}
        {step === 3 && track && (
          <div className="space-y-5">
            <div>
              <h2 className="text-base font-bold sm:text-lg">Assign Clips to Variations</h2>
              <p className="text-sm text-muted-foreground">Select one or more variations per clip, then confirm the assignment</p>
            </div>

            {track.clips.map((clip) => {
              const videoStatus = clip.video?.status;
              const assignedList = assignedClips[clip.id] ?? [];
              const hasVideo = videoStatus === "done" || !!exportedBlobUrlByClip[clip.id];
              const pending = selectedVariations[clip.id] ?? [];
              const unassignedVariations = (artistDetail?.variations ?? []).filter(
                (v: any) => !assignedList.some((a) => a.variationId === v.id)
              );

              const toggleVariation = (variationId: number) => {
                setSelectedVariations((s) => {
                  const cur = s[clip.id] ?? [];
                  return {
                    ...s,
                    [clip.id]: cur.includes(variationId)
                      ? cur.filter((id) => id !== variationId)
                      : [...cur, variationId],
                  };
                });
              };

              return (
                <div key={clip.id} className="rounded-2xl border border-border bg-card p-4 sm:p-5">
                  {/* Header row */}
                  <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <p className="font-semibold">Clip {clip.clip_index + 1}</p>
                      <p className="text-xs text-muted-foreground">{formatTime(clip.start_s)} – {formatTime(clip.end_s)}</p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      {videoStatus === "done" && clip.video?.video_path && (
                        <a
                          href={fileUrl(clip.video.video_path)}
                          download={`clip_${clip.clip_index + 1}.mp4`}
                          className="flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1 text-xs text-muted-foreground hover:border-foreground/40 hover:text-foreground transition-colors"
                        >
                          <Download className="h-3.5 w-3.5" /> Download
                        </a>
                      )}
                      {!hasVideo && (
                        <span className="rounded-full border border-yellow-500/30 bg-yellow-500/10 px-2 py-0.5 text-xs text-yellow-500">
                          {videoStatus === "generating" ? "Generating…" : "No video yet"}
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Already-assigned badges */}
                  {assignedList.length > 0 && (
                    <div className="mb-3 flex flex-wrap gap-1.5">
                      {assignedList.map((a) => (
                        <span key={a.variationId} className="flex items-center gap-1 rounded-full border border-green-500/30 bg-green-500/10 px-2.5 py-1 text-xs text-green-600">
                          <CheckCircle2 className="h-3 w-3" /> {a.variationName}
                        </span>
                      ))}
                    </div>
                  )}

                  {hasVideo && (
                    <div>
                      {unassignedVariations.length > 0 ? (
                        <>
                          <p className="mb-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">
                            {assignedList.length > 0 ? "Assign to more variations" : "Choose variations"}
                          </p>
                          <div className="flex flex-wrap gap-2">
                            {unassignedVariations.map((v: any) => {
                              const isSelected = pending.includes(v.id);
                              return (
                                <button
                                  key={v.id}
                                  onClick={() => toggleVariation(v.id)}
                                  disabled={assigning[clip.id]}
                                  className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm transition-colors disabled:opacity-50 ${
                                    isSelected
                                      ? "border-foreground bg-foreground text-background"
                                      : "border-border bg-background hover:border-foreground/40 hover:bg-foreground/5"
                                  }`}
                                >
                                  {isSelected
                                    ? <CheckCircle2 className="h-3.5 w-3.5" />
                                    : <User className="h-3.5 w-3.5 text-muted-foreground" />}
                                  {v.name}
                                </button>
                              );
                            })}
                          </div>
                          {pending.length > 0 && (
                            <button
                              onClick={() => {
                                const variations = pending.map((id: number) => {
                                  const v = artistDetail.variations.find((x: any) => x.id === id);
                                  return { id, name: v?.name ?? String(id) };
                                });
                                handleAssign(clip.id, variations);
                              }}
                              disabled={assigning[clip.id]}
                              className="mt-3 flex items-center gap-2 rounded-lg bg-foreground px-4 py-2 text-sm font-medium text-background hover:bg-foreground/90 transition-colors disabled:opacity-50"
                            >
                              {assigning[clip.id]
                                ? <><Loader2 className="h-3.5 w-3.5 animate-spin" /> Assigning…</>
                                : <><CheckCircle2 className="h-3.5 w-3.5" /> Assign to {pending.length} variation{pending.length > 1 ? "s" : ""}</>}
                            </button>
                          )}
                        </>
                      ) : (
                        <p className="text-xs text-muted-foreground">Assigned to all variations</p>
                      )}
                      {!artistDetail?.variations?.length && (
                        <p className="text-sm text-muted-foreground">No variations found</p>
                      )}
                    </div>
                  )}
                </div>
              );
            })}

            <div className="flex items-center justify-between pt-1">
              <button onClick={() => setStep(2)} className="flex items-center gap-2 rounded-lg border border-border px-4 py-2.5 text-sm">
                <ChevronLeft className="h-4 w-4" /> Back
              </button>
              <button
                onClick={() => {
                  setTrack(null);
                  setAudioFile(null);
                  setAudioTitle("");
                  setClipCount(1);
                  setClipConfigs({});
                  setClipWords({});
                  setAssignedClips({});
                  setStep(0);
                }}
                className="rounded-lg bg-foreground px-4 py-2.5 text-sm font-medium text-background"
              >
                New Track
              </button>
            </div>
          </div>
        )}
      </div>
    </div>

    {/* ── Recording Modal ──────────────────────────────────────────────── */}
    {isRecordingModalOpen && (() => {
      const recClip = pendingExportClipRef.current ?? activeClip;
      if (!recClip) return null;
      const recCfg      = clipConfigs[recClip.id] ?? { template_id: "minimal", lyrics_mode: "karaoke" };
      const recThemeId  = (recCfg.template_id || "minimal") as ThemeId;
      const recTheme    = OVERLAY_THEMES[recThemeId] ?? OVERLAY_THEMES.minimal;
      const recBgUrl    = recCfg.bg_path    ? fileUrl(recCfg.bg_path)    : null;
      const recCoverUrl = recCfg.cover_path ? fileUrl(recCfg.cover_path) : null;
      const recLyricsMode = recCfg.lyrics_mode ?? "karaoke";
      const isPreviewPhase = !isExportRecording;
      return (
        <div className="fixed inset-0 z-[100] bg-black flex flex-col">

          {/* ── TOP BAR — preview phase only; hidden during recording so captureTargetRef fills 100vh ── */}
          {isPreviewPhase && (
            <div className="shrink-0 h-12 flex items-center justify-between px-4"
                 style={{ background: "rgba(0,0,0,0.8)" }}>
              <span className="text-sm text-white/80 font-medium">Preview — position your crop then click Start Exporting</span>
              <button
                onClick={() => {
                  setIsRecordingModalOpen(false);
                  pendingExportClipRef.current = null;
                  if (audioPreviewRef.current) audioPreviewRef.current.pause();
                }}
                className="text-white/60 hover:text-white text-xs font-medium px-3 py-1 rounded-lg border border-white/20 hover:border-white/40 transition-colors"
              >
                Cancel
              </button>
            </div>
          )}

          {/* ── PREVIEW AREA — captureTargetRef is the crop target ──
               Layout: captureTarget is always sized to (100vh - 48px) so its
               position never shifts when the bottom bar appears/disappears.
               The bottom "Start Exporting" bar is absolutely positioned so it
               doesn't affect the flex layout. ── */}
          <div className="flex-1 relative bg-black flex items-center justify-center">

            {/* The actual capture target — sized consistently in both phases.
                outline is drawn on the element itself so the guide can never
                diverge from the actually-cropped region. */}
            <div
              ref={captureTargetRef}
              style={{
                aspectRatio: "9/16",
                // During recording the top bar is hidden, so fill the full viewport height.
                // This makes srcY ≈ 0 in the canvas-crop calculation — no offset error.
                height: isExportRecording ? "100vh" : "calc(100vh - 48px)",
                maxWidth: isExportRecording ? "calc(100vh * 9 / 16)" : "calc((100vh - 48px) * 9 / 16)",
                overflow: "hidden",
                position: "relative",
                outline: isPreviewPhase ? "2px dashed rgba(255,255,255,0.55)" : "none",
                outlineOffset: "-2px",
              }}
            >
              <PreviewContent
                themeId={recThemeId}
                theme={recTheme}
                bgImageUrl={recBgUrl}
                coverImageUrl={recCoverUrl}
                lyricLines={activeKaraokeLyrics}
                isPlaying={true}
                overlayLineIndex={overlayLineIndex}
                overlayWordIndex={overlayWordIndex}
                lyricsMode={recLyricsMode}
                coverArtRef={coverArtRef}
              />
            </div>

            {/* Crop frame — purely decorative, pointer-events-none, never recorded */}
            {isPreviewPhase && (
              <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                <div style={{
                  aspectRatio: "9/16",
                  height: "calc(100vh - 48px)",
                  maxWidth: "calc((100vh - 48px) * 9 / 16)",
                  position: "relative",
                }} /* preview phase only — isExportRecording is false here */>

                  {([
                    { top: -4, left: -4, borderTop: "3px solid white", borderLeft: "3px solid white", borderRadius: "3px 0 0 0" },
                    { top: -4, right: -4, borderTop: "3px solid white", borderRight: "3px solid white", borderRadius: "0 3px 0 0" },
                    { bottom: -4, left: -4, borderBottom: "3px solid white", borderLeft: "3px solid white", borderRadius: "0 0 0 3px" },
                    { bottom: -4, right: -4, borderBottom: "3px solid white", borderRight: "3px solid white", borderRadius: "0 0 3px 0" },
                  ] as React.CSSProperties[]).map((s, i) => (
                    <div key={i} style={{ position: "absolute", width: 18, height: 18, ...s }} />
                  ))}
                  <div style={{
                    position: "absolute", top: 12, left: "50%", transform: "translateX(-50%)",
                    fontSize: 11, color: "rgba(255,255,255,0.6)", whiteSpace: "nowrap",
                    background: "rgba(0,0,0,0.55)", padding: "2px 8px", borderRadius: 4,
                  }}>
                    Only this region is recorded
                  </div>
                </div>
              </div>
            )}
          </div>{/* end flex-1 preview area */}

          {/* ── Start Exporting panel — preview phase only, right-side fixed ── */}
          {isPreviewPhase && (
            <div style={{
              position: "fixed", right: 24, top: "50%", transform: "translateY(-50%)",
              zIndex: 200,
              display: "flex", flexDirection: "column", alignItems: "center", gap: 12,
            }}>
              <button
                onClick={() => {
                  if (pendingExportClipRef.current) handleBeginRecording(pendingExportClipRef.current);
                }}
                style={{
                  background: "white", color: "black", border: "none", cursor: "pointer",
                  padding: "14px 20px", borderRadius: 12, fontWeight: 700, fontSize: 14,
                  whiteSpace: "nowrap", display: "flex", alignItems: "center", gap: 8,
                  boxShadow: "0 4px 20px rgba(0,0,0,0.5)",
                }}
              >
                <span style={{ width: 10, height: 10, borderRadius: "50%", background: "red", display: "inline-block", flexShrink: 0 }} />
                Start Exporting
              </button>
            </div>
          )}

          {/* ── Recording indicator — shown during export, fixed top-left, OUTSIDE captureTargetRef ──
               captureTargetRef is centered in the viewport, so this corner badge is NOT in the crop rect
               (it overlaps the black letterbox area on a widescreen display). ── */}
          {isExportRecording && (
            <div style={{
              position: "fixed", top: 12, left: 16, zIndex: 300,
              display: "flex", alignItems: "center", gap: 8,
              background: "rgba(0,0,0,0.75)", borderRadius: 8, padding: "6px 12px",
              pointerEvents: "none",
            }}>
              <span style={{ width: 8, height: 8, borderRadius: "50%", background: "red", flexShrink: 0, animation: "pulse 1s infinite" }} />
              <span style={{ color: "white", fontSize: 12, fontWeight: 600 }}>Recording… keep this tab in front</span>
              <div style={{ width: 80, height: 4, background: "rgba(255,255,255,0.2)", borderRadius: 4, overflow: "hidden" }}>
                <div style={{ height: "100%", width: `${exportProgress}%`, background: "red", transition: "width 0.2s linear" }} />
              </div>
            </div>
          )}
        </div>
      );
    })()}

    {/* ── Export Info Modal (themed, replaces browser alert) ──────────── */}
    {exportInfoModal && (
      <div className="fixed inset-0 z-[110] flex items-center justify-center p-4">
        <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setExportInfoModal(null)} />
        <div className="relative w-full max-w-sm rounded-2xl border border-border bg-card p-6 shadow-2xl">
          <h3 className="text-base font-semibold mb-2">{exportInfoModal.title}</h3>
          <p className="text-sm text-muted-foreground mb-6">{exportInfoModal.message}</p>
          <div className="flex justify-end">
            <button
              onClick={() => setExportInfoModal(null)}
              className="rounded-xl bg-foreground px-5 py-2 text-sm font-semibold text-background hover:bg-foreground/90 transition-colors"
            >
              OK
            </button>
          </div>
        </div>
      </div>
    )}

    {/* ── Export Preview Modal ─────────────────────────────────────────── */}
    {exportedBlobUrl && (
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        {/* Backdrop */}
        <div
          className="absolute inset-0 bg-black/60 backdrop-blur-sm"
          onClick={() => { setExportedBlobUrl(null); setExportedBlob(null); }}
        />

        {/* Panel */}
        <div className="relative flex flex-col w-full max-w-sm rounded-2xl border border-border bg-card shadow-2xl overflow-hidden">

          {/* Header */}
          <div className="flex items-center justify-between px-5 py-4 border-b border-border">
            <div>
              <p className="font-semibold text-base text-foreground">Clip {exportClipIndex + 1} — Ready</p>
              <p className="text-xs text-muted-foreground mt-0.5">Watch, then download or assign to a variation</p>
            </div>
            <button
              onClick={() => { setExportedBlobUrl(null); setExportedBlob(null); }}
              className="p-1.5 rounded-lg hover:bg-muted transition-colors text-muted-foreground hover:text-foreground"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </div>

          {/* Video preview */}
          <div className="bg-black aspect-[9/16] max-h-[60vh] flex items-center justify-center relative">
            <video
              key={exportedBlobUrl}
              src={exportedBlobUrl ?? undefined}
              controls
              autoPlay
              playsInline
              className="w-full h-full object-contain"
              onError={(e) => {
                const el = e.currentTarget;
                el.style.display = "none";
                const parent = el.parentElement;
                if (parent && !parent.querySelector(".video-error-msg")) {
                  const msg = document.createElement("div");
                  msg.className = "video-error-msg";
                  msg.style.cssText = "color:#fff;text-align:center;padding:24px;font-size:13px;line-height:1.6";
                  msg.innerHTML = "<div style='font-size:32px;margin-bottom:8px'>⚠️</div><strong>Video not available</strong><br><span style='opacity:0.7'>The file may have been deleted.<br>Re-record and assign to restore it.</span>";
                  parent.appendChild(msg);
                }
              }}
            />
          </div>

          {/* Actions */}
          <div className="grid grid-cols-2 gap-3 p-4">
            <button
              disabled={convertingMp4}
              onClick={async () => {
                const filename = `clip_${exportClipIndex + 1}.mp4`;

                // Server-stored video: already MP4, download directly
                if (!exportedBlob && exportedBlobUrl) {
                  triggerDownload(exportedBlobUrl, filename);
                  return;
                }

                if (!exportedBlob) return;
                setConvertingMp4(true);
                try {
                  const formData = new FormData();
                  formData.append("file", exportedBlob, `clip_${exportClipIndex + 1}.webm`);
                  const token = localStorage.getItem("icreate_token");
                  const res = await fetch("/api/audio-to-video/convert-to-mp4", {
                    method: "POST",
                    body: formData,
                    headers: token ? { Authorization: `Bearer ${token}` } : {},
                  });
                  if (!res.ok) throw new Error(await res.text());
                  const mp4Blob = await res.blob();
                  const url = URL.createObjectURL(mp4Blob);
                  triggerDownload(url, filename);
                  URL.revokeObjectURL(url);
                } catch (err: any) {
                  setExportInfoModal({ title: "Conversion failed", message: err?.message ?? "Unknown error" });
                } finally {
                  setConvertingMp4(false);
                }
              }}
              className="w-full flex items-center justify-center gap-2 py-3 px-3 bg-foreground text-background font-semibold rounded-xl hover:bg-foreground/90 transition-colors text-sm disabled:opacity-60"
            >
              {convertingMp4
                ? <><Loader2 className="w-4 h-4 shrink-0 animate-spin" /><span className="truncate">Converting…</span></>
                : <><Download className="w-4 h-4 shrink-0" /><span className="truncate">Download MP4</span></>}
            </button>
            <button
              onClick={async () => {
                if (!exportedBlob || exportClipIdRef.current == null) {
                  setStep(3);
                  return;
                }
                setUploadingExport(true);
                try {
                  // Convert WebM → MP4 on the server before saving
                  const rawName = `clip_${exportClipIndex + 1}`;
                  const token = localStorage.getItem("icreate_token");
                  const formData = new FormData();
                  formData.append("file", exportedBlob, `${rawName}.webm`);
                  const res = await fetch("/api/audio-to-video/convert-to-mp4", {
                    method: "POST",
                    body: formData,
                    headers: token ? { Authorization: `Bearer ${token}` } : {},
                  });
                  if (!res.ok) throw new Error(await res.text());
                  const mp4Blob = await res.blob();
                  const saved = await uploadAudioClipVideo(exportClipIdRef.current, mp4Blob, "mp4", `${rawName}.mp4`);
                  // Keep View Last Export alive using the now-persisted server URL
                  if (saved?.video_path) {
                    const serverUrl = `/api/files/${saved.video_path}`;
                    setExportedBlobUrlByClip((prev) => ({ ...prev, [exportClipIdRef.current!]: serverUrl }));
                  }
                } catch (err: any) {
                  setExportInfoModal({ title: "Upload failed", message: err?.response?.data?.detail || err?.message || "Unknown error" });
                  setUploadingExport(false);
                  return;
                }
                setUploadingExport(false);
                setExportedBlobUrl(null);
                setExportedBlob(null);
                setStep(3);
              }}
              disabled={uploadingExport || convertingMp4}
              className="w-full flex items-center justify-center gap-2 py-3 px-3 border border-border text-foreground font-semibold rounded-xl hover:bg-muted transition-colors text-sm disabled:opacity-50"
            >
              {uploadingExport
                ? <><Loader2 className="w-4 h-4 shrink-0 animate-spin" /><span className="truncate">Uploading…</span></>
                : <><MonitorPlay className="w-4 h-4 shrink-0" /><span className="truncate">Assign to Variation</span></>}
            </button>
          </div>

        </div>
      </div>
    )}
    </>
  );
}
