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
  updateAudioClipLyrics,
  assignAudioClip,
  uploadAudioClipAsset,
  uploadAudioClipVideo,
} from "@/lib/api";
import { createCanvasRenderer, type LayerOverrides } from "./canvasRenderer";
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
}

interface AudioTrackData {
  id: number;
  title: string;
  duration_s: number;
  words: AudioWord[];
  clips: AudioClipData[];
}

interface TrackSummary {
  id: number;
  title: string;
  duration_s: number;
  created_at?: string;
}

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

// ─── Layer-capture helpers ────────────────────────────────────────────────────

/**
 * Fetch every <img> inside `root`, replace its src with a same-origin blob URL,
 * and return a cleanup function that restores the original srcs.
 *
 * html-to-image renders via SVG foreignObject. Browsers refuse to serialize
 * <img> elements that were loaded WITHOUT crossOrigin="anonymous", so any image
 * served from the API (/api/files/…) shows up blank in the capture. Replacing
 * the src with a blob: URL (which is always same-origin) lets the library embed
 * them correctly without touching the visible page.
 */
async function inlineImagesAsBlobURLs(root: HTMLElement): Promise<() => void> {
  const imgs = Array.from(root.querySelectorAll<HTMLImageElement>("img[src]"));
  const blobURLs: string[] = [];
  const origSrcs: string[] = [];

  await Promise.all(
    imgs.map(async (img, i) => {
      const src = img.src;
      if (!src || src.startsWith("data:") || src.startsWith("blob:")) return;
      try {
        const res = await fetch(src, { credentials: "include" });
        if (!res.ok) return;
        const blob = await res.blob();
        const blobURL = URL.createObjectURL(blob);
        blobURLs.push(blobURL);
        origSrcs[i] = src;
        img.src = blobURL;
        // Wait for the browser to swap the src so it's in place before capture
        try { await img.decode(); } catch { /* ignore */ }
      } catch { /* skip failed fetches */ }
    })
  );

  return () => {
    imgs.forEach((img, i) => { if (origSrcs[i]) img.src = origSrcs[i]; });
    blobURLs.forEach(u => URL.revokeObjectURL(u));
  };
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
  const exportClipIdRef = useRef<number | null>(null);
  const exportAudioCtxRef = useRef<AudioContext | null>(null);
  // Persists blob URLs per clip so "View Export" button can reopen the modal
  const [exportedBlobUrlByClip, setExportedBlobUrlByClip] = useState<Record<number, string>>({});
  // WebGL render mode — "match" = exact HTML fidelity, "upgraded" = bloom + soft particles
  const [renderMode, setRenderMode] = useState<"match" | "upgraded">("match");

  // Overlay preview karaoke state
  const [overlayLineIndex, setOverlayLineIndex] = useState(0);
  const [overlayWordIndex, setOverlayWordIndex] = useState(-1);

  // Assign state — a clip can be assigned to multiple variations
  const [assignedClips, setAssignedClips] = useState<Record<number, Array<{ variationId: number; variationName: string }>>>({});
  const [assigning, setAssigning] = useState<Record<number, boolean>>({});

  // Confirm modal state
  const [confirmModal, setConfirmModal] = useState<{
    title: string;
    message: string;
    onConfirm: () => void;
  } | null>(null);

  const activeClip = track?.clips.find((c) => c.id === editingClipId) ?? track?.clips[0] ?? null;

  const showConfirm = (title: string, message: string): Promise<boolean> =>
    new Promise((resolve) => {
      setConfirmModal({
        title,
        message,
        onConfirm: () => { setConfirmModal(null); resolve(true); },
      });
    });

  // Poll interval ref
  const pollRef = useRef<NodeJS.Timeout | null>(null);

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
      const configs: Record<number, { template_id: string; bg_path?: string; cover_path?: string }> = {};
      const words: Record<number, AudioWord[]> = {};
      // trackData.clips don't carry per-clip words; distribute from the flat
      // trackData.words array (each word has a clip_index field from the DB).
      for (const clip of trackData.clips) {
        configs[clip.id] = {
          template_id: clip.video?.template_id ?? "minimal",
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
      if (trackData.clips.length > 0) setEditingClipId(trackData.clips[0].id);
      setActiveReviewClip(0);
      setStep(1);
    } catch (e: any) {
      alert(e?.response?.data?.detail || "Failed to load track");
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
      alert(e?.response?.data?.detail || "Failed to delete track");
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
      const configs: Record<number, { template_id: string; bg_path?: string; cover_path?: string }> = {};
      const words: Record<number, AudioWord[]> = {};
      // Distribute flat trackData.words to each clip by clip_index
      for (const clip of trackData.clips) {
        configs[clip.id] = {
          template_id: clip.video?.template_id ?? "minimal",
          bg_path: clip.video?.background_image_path ?? undefined,
          cover_path: clip.video?.album_cover_path ?? undefined,
        };
        words[clip.id] = (trackData.words ?? []).filter(
          (w: any) => w.clip_index === clip.clip_index,
        );
      }
      setClipConfigs(configs);
      setClipWords(words);
      if (trackData.clips.length > 0) setEditingClipId(trackData.clips[0].id);
      // Refresh past tracks list
      if (selectedArtistId) loadPastTracks(selectedArtistId);
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
      await generateAudioVideoClip(clipId, cfg.template_id, cfg.bg_path, cfg.cover_path);
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
          // When generation finishes successfully, clear dirty flag
          if (status === "done") {
            setClipConfigDirty((d) => ({ ...d, [c.id]: false }));
            // Auto-download if this clip was queued for it
            setAutoDownloadClipId((prev) => {
              if (prev === c.id && c.video?.video_path) {
                const a = document.createElement("a");
                a.href = fileUrl(c.video.video_path);
                a.download = `clip_${c.clip_index + 1}.mp4`;
                a.click();
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

  // ── Overlay karaoke preview — timeupdate-driven sync ─────────────────────

  // Reset karaoke on clip change; pause audio
  useEffect(() => {
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

  // flat index → { lineIdx, wordIdx } — built once per lyrics change
  const wordPositionMap = useMemo(() => {
    const map: Array<{ lineIdx: number; wordIdx: number }> = [];
    activeKaraokeLyrics.forEach((line, li) =>
      line.forEach((_, wi) => map.push({ lineIdx: li, wordIdx: wi }))
    );
    return map;
  }, [activeKaraokeLyrics]);

  // Ref so handler can read latest map without re-attaching
  const wordPositionMapRef = useRef(wordPositionMap);
  useEffect(() => { wordPositionMapRef.current = wordPositionMap; }, [wordPositionMap]);

  // RAF-based karaoke sync — polls at ~60fps, reads fresh refs each frame
  useEffect(() => {
    let rafId: number;

    const tick = () => {
      const audio = audioPreviewRef.current;
      const clip  = activeClipRef.current;

      if (audio && clip && !audio.paused) {
        // Whisper timestamps are absolute from full track start.
        // audio.currentTime is relative to the clip segment (starts at 0).
        const t  = audio.currentTime + (clip.start_s ?? 0);
        const ws = clipWordsRef.current[clip.id] ?? [];

        if (ws.length > 0) {
          // "Last started word" approach — far more reliable than Whisper's end_s
          // (many words have end_s = start_s = 0ms duration, making range checks impossible).
          // Simply find the last word whose start_s has been reached.
          let idx = -1;
          for (let i = 0; i < ws.length; i++) {
            if (ws[i].start_s <= t) idx = i;
            else break; // words are sorted by start_s — stop early
          }

          if (idx !== -1) {
            const pos = wordPositionMapRef.current[idx];
            if (pos) {
              setOverlayLineIndex(pos.lineIdx);
              setOverlayWordIndex(pos.wordIdx);
            }
          }
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

  /** Save lyrics from textarea: split lines→words, update word text (keeps timestamps) */
  const handleSaveLyricsText = async (clipId: number) => {
    const text  = getLyricsText(clipId);
    const newWords = text.split(/\s+/).filter(Boolean);
    const existing = clipWords[clipId] ?? [];
    const merged: AudioWord[] = newWords.map((word, i) => ({
      ...(existing[i] ?? { start_s: 0, end_s: 0 }),
      word,
    }));
    setClipWords((cw) => ({ ...cw, [clipId]: merged }));
    setSavingLyrics(true);
    try {
      await updateAudioClipLyrics(clipId, merged);
    } catch (err: any) {
      alert(err?.response?.data?.detail || "Failed to save lyrics");
    } finally {
      setSavingLyrics(false);
    }
  };

  const handleSaveLyrics = async (clipId: number) => {
    const words = clipWords[clipId] ?? [];
    setSavingLyrics(true);
    try {
      await updateAudioClipLyrics(clipId, words);
    } catch (err: any) {
      alert(err?.response?.data?.detail || "Failed to save lyrics");
    } finally {
      setSavingLyrics(false);
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
      alert("Upload failed: " + (err?.response?.data?.detail || err.message));
    } finally {
      setUploadingAsset((u) => ({ ...u, [assetKey]: false }));
    }
  };

  // ── Assign to variation ───────────────────────────────────────────────────

  const handleAssign = async (clipId: number, variationId: number, variationName: string) => {
    const already = assignedClips[clipId] ?? [];
    if (already.some((a) => a.variationId === variationId)) return;
    setAssigning((a) => ({ ...a, [clipId]: true }));
    try {
      await assignAudioClip(clipId, variationId);
      setAssignedClips((ac) => ({
        ...ac,
        [clipId]: [...(ac[clipId] ?? []), { variationId, variationName }],
      }));
    } catch (err: any) {
      alert(err?.response?.data?.detail || "Failed to assign clip");
    } finally {
      setAssigning((a) => ({ ...a, [clipId]: false }));
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
                  <span className="text-sm">Uploading & transcribing…</span>
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
                <button
                  onClick={handleGenerateAll}
                  className="flex w-full items-center justify-center gap-2 rounded-lg bg-foreground px-4 py-2.5 text-sm font-medium text-background sm:w-auto"
                >
                  <Wand2 className="h-4 w-4" />
                  Generate All
                </button>
              </div>
            </div>

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
                        {formatTime(clip.start_s)} – {formatTime(clip.end_s)} · {clip.words?.length ?? 0} words
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
                      <button
                        onClick={() => handleGenerateClip(clip.id)}
                        disabled={isGenerating}
                        className="flex items-center gap-1.5 rounded-lg border border-foreground/30 bg-foreground/10 px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-foreground/20 disabled:opacity-50"
                      >
                        {isGenerating
                          ? <><Loader2 className="h-3.5 w-3.5 animate-spin" /> Generating…</>
                          : <><Wand2 className="h-3.5 w-3.5" /> {videoStatus === "done" ? "Regenerate" : "Generate"}</>}
                      </button>
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
          const cfg        = clipConfigs[activeClip?.id ?? -1] ?? { template_id: "minimal" };
          const lyricsText = activeClip ? getLyricsText(activeClip.id) : "";
          const isGen      = !!(activeClip && (generating[activeClip.id] || activeClip.video?.status === "generating"));
          const themeId    = (cfg.template_id || "minimal") as ThemeId;
          const theme      = OVERLAY_THEMES[themeId] ?? OVERLAY_THEMES.minimal;
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
                    <div>
                      <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2 block">
                        Lyrics Content
                      </label>
                      <textarea
                        value={lyricsText}
                        onChange={(e) => {
                          setClipLyricsText((lt) => ({ ...lt, [activeClip.id]: e.target.value }));
                          if (activeClip.video?.status === "done") {
                            setClipConfigDirty((d) => ({ ...d, [activeClip.id]: true }));
                          }
                        }}
                        className="w-full h-32 bg-background border border-border rounded-xl p-3 text-sm text-foreground focus:outline-none focus:border-foreground/60/50 resize-none font-medium [&::-webkit-scrollbar]:hidden"
                        style={{ scrollbarWidth: "none" }}
                        placeholder="Enter lyrics here..."
                      />
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
                              if (activeClip.video?.status === "done") {
                                setClipConfigDirty((d) => ({ ...d, [activeClip.id]: true }));
                              }
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

                      <div className="flex gap-3">
                        <button
                          onClick={() => {
                            const next = !isPreviewPaused;
                            setIsPreviewPaused(!isPreviewPaused);
                            if (audioPreviewRef.current) {
                              if (next) audioPreviewRef.current.pause();
                              else audioPreviewRef.current.play().catch(() => {});
                            }
                          }}
                          className="flex-1 flex items-center justify-center gap-2 py-3.5 bg-muted text-foreground font-semibold rounded-xl hover:bg-muted/80 transition-colors"
                        >
                          {isPreviewPaused
                            ? <><Play className="w-4 h-4 fill-current" /> Play Preview</>
                            : <><Pause className="w-4 h-4 fill-current" /> Pause Preview</>}
                        </button>

                        {/* WebGL Export — canvas.captureStream + MediaRecorder */}
                        {isExportRecording ? (
                          <button disabled className="flex-1 flex items-center justify-center gap-2 py-3.5 bg-foreground/80 text-background font-semibold rounded-xl">
                            <Loader2 className="w-4 h-4 animate-spin" />
                            Recording… {exportProgress}%
                          </button>
                        ) : (
                          <button
                            onClick={async () => {
                              const clip = activeClip;
                              if (!clip || !clip.local_path) return;
                              const clipCfg = clipConfigs[clip.id] ?? { template_id: "minimal" };
                              const tid2 = (clipCfg.template_id ?? "minimal") as ThemeId;
                              const theme2 = OVERLAY_THEMES[tid2] ?? OVERLAY_THEMES.minimal;
                              const bgImageUrl = clipCfg.bg_path ? fileUrl(clipCfg.bg_path) : null;
                              const coverImageUrl = clipCfg.cover_path ? fileUrl(clipCfg.cover_path) : null;
                              const words2 = clipWords[clip.id] ?? [];
                              const clipDuration = clip.end_s - clip.start_s;

                              setIsExportRecording(true);
                              setExportProgress(0);
                              exportAbortRef.current = false;
                              setGenerationErrors((e) => ({ ...e, [clip.id]: "" }));

                              try {
                                // ── Layer-composite capture for "match" mode ──
                                let layerOverrides: LayerOverrides | undefined;
                                if (renderMode === "match") {
                                  const { toCanvas } = await import("html-to-image");
                                  const previewEl = previewCanvasRef.current!;
                                  const pixelRatio = 1080 / previewEl.offsetWidth;

                                  // Spin durations per theme (null = no separate spinning cover)
                                  const SPIN: Record<string, number | null> = {
                                    minimal: 20, neon: 5, vivid: null, inferno: null,
                                  };
                                  const spinDuration = SPIN[tid2] ?? null;
                                  const hasCoverSpin = spinDuration !== null;

                                  // Measure cover element position before hiding anything
                                  let coverCX = 0, coverCY = 0, coverCW = 0, coverCH = 0;
                                  let capturedCoverCanvas = document.createElement("canvas");
                                  const coverEl = hasCoverSpin ? coverArtRef.current : null;

                                  if (coverEl) {
                                    const previewRect = previewEl.getBoundingClientRect();
                                    const coverRect   = coverEl.getBoundingClientRect();
                                    coverCW = coverRect.width  * pixelRatio;
                                    coverCH = coverRect.height * pixelRatio;
                                    coverCX = (coverRect.left - previewRect.left + coverRect.width  / 2) * pixelRatio;
                                    coverCY = (coverRect.top  - previewRect.top  + coverRect.height / 2) * pixelRatio;

                                    // Pre-fetch images so html-to-image can embed them
                                    const restoreCoverImgs = await inlineImagesAsBlobURLs(coverEl);
                                    // Capture cover element as PNG (at export resolution)
                                    capturedCoverCanvas = await toCanvas(coverEl, {
                                      width: coverRect.width,
                                      height: coverRect.height,
                                      pixelRatio,
                                      skipFonts: true,
                                    });
                                    restoreCoverImgs();
                                  }

                                  // Hide cover + zigzag + lyrics before capturing the layer canvas
                                  if (coverEl) coverEl.style.visibility = "hidden";
                                  if (zigzagLayerRef.current) zigzagLayerRef.current.style.visibility = "hidden";
                                  if (lyricsLayerRef.current) lyricsLayerRef.current.style.visibility = "hidden";

                                  // Pre-fetch images in the full preview so html-to-image can embed them
                                  const restorePreviewImgs = await inlineImagesAsBlobURLs(previewEl);

                                  // Temporarily remove border-radius so capture is a clean rectangle
                                  const savedBR = previewEl.style.borderRadius;
                                  previewEl.style.borderRadius = "0";

                                  const capturedLayerCanvas = await toCanvas(previewEl, {
                                    width:  previewEl.offsetWidth,
                                    height: previewEl.offsetHeight,
                                    pixelRatio,
                                    skipFonts: true,
                                  });

                                  // Restore
                                  previewEl.style.borderRadius = savedBR;
                                  restorePreviewImgs();
                                  if (coverEl) coverEl.style.visibility = "visible";
                                  if (zigzagLayerRef.current) zigzagLayerRef.current.style.visibility = "visible";
                                  if (lyricsLayerRef.current) lyricsLayerRef.current.style.visibility = "visible";

                                  layerOverrides = {
                                    layerCanvas: capturedLayerCanvas,
                                    coverCanvas: capturedCoverCanvas,
                                    coverCX, coverCY, coverCW, coverCH,
                                    spinDuration,
                                  };
                                }

                                const renderer = await createCanvasRenderer({
                                  width: 1080, height: 1920,
                                  themeId: tid2, theme: theme2,
                                  words: words2, bgImageUrl, coverImageUrl,
                                  clipStartS: clip.start_s,
                                  clipDuration,
                                  renderMode,
                                  layerOverrides,
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
                                const audioSrc = audioCtx.createMediaElementSource(recAudio);
                                const audioDest = audioCtx.createMediaStreamDestination();
                                audioSrc.connect(audioDest);
                                audioSrc.connect(audioCtx.destination);

                                const videoStream = renderer.canvas.captureStream(30);
                                const combined = new MediaStream([
                                  ...videoStream.getVideoTracks(),
                                  ...audioDest.stream.getAudioTracks(),
                                ]);
                                const mimeType = MediaRecorder.isTypeSupported("video/webm;codecs=vp9,opus")
                                  ? "video/webm;codecs=vp9,opus"
                                  : MediaRecorder.isTypeSupported("video/webm;codecs=vp8,opus")
                                  ? "video/webm;codecs=vp8,opus"
                                  : "video/webm";
                                const recorder = new MediaRecorder(combined, { mimeType, videoBitsPerSecond: 8_000_000 });
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
                                  const url = URL.createObjectURL(blob);
                                  setExportedBlobUrl(url);
                                  setExportedBlob(blob);
                                  setExportedExt("webm");
                                  setExportClipIndex(clip.clip_index);
                                  exportClipIdRef.current = clip.id;
                                  setExportedBlobUrlByClip((prev) => ({ ...prev, [clip.id]: url }));
                                  setExportProgress(100);
                                  setIsExportRecording(false);
                                };
                              } catch (err: any) {
                                console.error("WebGL export failed", err);
                                setGenerationErrors((e) => ({ ...e, [clip.id]: `Export failed: ${err?.message ?? "unknown"}` }));
                                setIsExportRecording(false);
                              }
                            }}
                            className="flex-1 flex items-center justify-center gap-2 py-3.5 bg-foreground text-background font-semibold rounded-xl hover:bg-foreground/90 transition-colors"
                          >
                            <Download className="w-4 h-4" /> Export Video
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

                    {/* Generate / Regenerate — always visible */}
                    <button
                      onClick={() => handleSaveLyricsText(activeClip.id).then(() => handleGenerateClip(activeClip.id))}
                      disabled={isGen || savingLyrics}
                      className="flex w-full items-center justify-center gap-2 rounded-xl border border-border py-2.5 text-sm text-muted-foreground hover:border-foreground/40 hover:text-foreground disabled:opacity-40 transition-colors"
                    >
                      {isGen
                        ? <><Loader2 className="h-3.5 w-3.5 animate-spin" /> Generating…</>
                        : activeClip.video?.status === "done"
                          ? <>
                              <RefreshCw className="h-3.5 w-3.5" />
                              {clipConfigDirty[activeClip.id]
                                ? <><span>Regenerate with new settings</span><span className="ml-1 rounded-full bg-amber-500/20 text-amber-500 text-[10px] px-1.5 py-0.5">Updated</span></>
                                : "Save lyrics & Regenerate"}
                            </>
                          : <><Wand2 className="h-3.5 w-3.5" /> Generate Video</>}
                    </button>
                  </div>

                  {/* ══ RIGHT: 9:16 Canvas (Figma Design) ═════════════════════ */}
                  <div className="flex flex-1 items-start justify-center pt-2">
                    <div ref={previewCanvasRef} className="relative w-full max-w-[360px] md:max-w-[420px] aspect-[9/16] bg-black rounded-[2.5rem] overflow-hidden shadow-2xl ring-4 ring-neutral-800 flex-shrink-0 isolate">

                      {/* Background / Environment Layer */}
                      <div className="absolute inset-0 z-0 bg-black">
                        {bgUrl ? (
                          <img
                            src={bgUrl}
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
                          <OverlayFlames isPlaying={!isPreviewPaused} />
                        ) : (
                          <OverlayParticles color={theme.accent} isPlaying={!isPreviewPaused} />
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
                              {themeId === "minimal" && <MinimalArt isPlaying={!isPreviewPaused} albumCover={coverUrl} coverRef={coverArtRef} />}
                              {themeId === "vivid" && <VividArt isPlaying={!isPreviewPaused} albumCover={coverUrl} />}
                              {themeId === "neon" && <NeonArt isPlaying={!isPreviewPaused} albumCover={coverUrl} coverRef={coverArtRef} />}
                              {themeId === "inferno" && <InfernoArt isPlaying={!isPreviewPaused} albumCover={coverUrl} />}
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
                            <clipPath id="zigzag-clip">
                              <motion.rect
                                x="0" y="0" height="30"
                                initial={{ width: "0%" }}
                                animate={{ width: !isPreviewPaused ? "100%" : "0%" }}
                                transition={{
                                  duration: lyricLines.length * 2.5 || 10,
                                  repeat: !isPreviewPaused ? Infinity : 0,
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
                            clipPath="url(#zigzag-clip)"
                            style={{ filter: `drop-shadow(0 0 6px ${theme.accent})` }}
                          />
                        </svg>
                      </div>

                      {/* 3. KARAOKE LYRICS — bottom third at top-[70.3%] */}
                      <div ref={lyricsLayerRef} className="absolute top-[70.3%] bottom-[5%] left-[8%] right-[8%] z-10 flex items-start justify-center overflow-hidden">
                        <AnimatePresence mode="wait">
                          {lyricLines.length > 0 && lyricLines[overlayLineIndex % lyricLines.length] && (
                            <motion.div
                              key={overlayLineIndex % lyricLines.length}
                              initial={{ opacity: 0, y: 10 }}
                              animate={{ opacity: 1, y: 0 }}
                              exit={{ opacity: 0, y: -10 }}
                              transition={{ duration: 0.12, ease: "easeOut" }}
                              className="text-center w-full"
                            >
                              <p className="text-3xl font-extrabold tracking-tight leading-[1.3] drop-shadow-xl flex flex-wrap justify-center gap-x-2 gap-y-1">
                                {lyricLines[overlayLineIndex % lyricLines.length].map((word: string, wIdx: number) => {
                                  const isHighlighted = !isPreviewPaused && wIdx === overlayWordIndex;
                                  const isPassed = !isPreviewPaused && wIdx < overlayWordIndex;

                                  return (
                                    <motion.span
                                      key={wIdx}
                                      initial={{
                                        color: isPassed ? "#ffffff" : "rgba(255,255,255,0.4)",
                                        textShadow: "0 4px 10px rgba(0,0,0,0.8)",
                                        scale: 1,
                                      }}
                                      animate={{
                                        color: isHighlighted
                                          ? theme.accent
                                          : isPassed ? "#ffffff" : "rgba(255,255,255,0.4)",
                                        textShadow: isHighlighted ? theme.textGlow : "0 4px 10px rgba(0,0,0,0.8)",
                                        scale: isHighlighted ? 1.05 : 1,
                                      }}
                                      transition={{ duration: 0.15 }}
                                      className="inline-block transition-colors"
                                    >
                                      {word}
                                    </motion.span>
                                  );
                                })}
                              </p>
                            </motion.div>
                          )}
                        </AnimatePresence>
                      </div>

                      {/* Generating overlay */}
                      {isGen && (
                        <div className="absolute inset-0 z-20 flex flex-col items-center justify-center bg-black/60 backdrop-blur-sm">
                          <Loader2 className="h-10 w-10 animate-spin text-foreground" />
                          <p className="mt-3 text-sm text-white/60">Generating video...</p>
                        </div>
                      )}
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
              <p className="text-sm text-muted-foreground">Assign each generated clip to an artist variation for scheduling</p>
            </div>

            {track.clips.map((clip) => {
              const videoStatus = clip.video?.status;
              const assignedList = assignedClips[clip.id] ?? [];
              const hasVideo = videoStatus === "done" || !!exportedBlobUrlByClip[clip.id];

              return (
                <div key={clip.id} className="rounded-2xl border border-border bg-card p-4 sm:p-5">
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
                      {assignedList.map((a) => (
                        <span key={a.variationId} className="flex items-center gap-1 rounded-full border border-green-500/30 bg-green-500/10 px-2 py-0.5 text-xs text-green-500">
                          <CheckCircle2 className="h-3 w-3" /> {a.variationName}
                        </span>
                      ))}
                    </div>
                  </div>

                  {hasVideo && (
                    <div>
                      <p className="mb-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">Choose Variation</p>
                      <div className="flex flex-wrap gap-2">
                        {artistDetail?.variations?.map((v: any) => {
                          const isAlreadyAssigned = assignedList.some((a) => a.variationId === v.id);
                          return (
                            <button
                              key={v.id}
                              onClick={() => handleAssign(clip.id, v.id, v.name)}
                              disabled={assigning[clip.id] || isAlreadyAssigned}
                              className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm transition-colors disabled:opacity-50 ${
                                isAlreadyAssigned
                                  ? "border-green-500/40 bg-green-500/10 text-green-500 cursor-default"
                                  : "border-border bg-background hover:border-foreground/40 hover:bg-foreground/5"
                              }`}
                            >
                              {assigning[clip.id] && !isAlreadyAssigned
                                ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                : isAlreadyAssigned
                                ? <CheckCircle2 className="h-3.5 w-3.5" />
                                : <User className="h-3.5 w-3.5 text-muted-foreground" />}
                              {v.name}
                            </button>
                          );
                        })}
                        {!artistDetail?.variations?.length && (
                          <p className="text-sm text-muted-foreground">No variations found</p>
                        )}
                      </div>
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
          <div className="bg-black aspect-[9/16] max-h-[60vh] flex items-center justify-center">
            <video
              controls
              autoPlay
              playsInline
              className="w-full h-full object-contain"
            >
              <source src={exportedBlobUrl} type="video/mp4" />
              <source src={exportedBlobUrl} type="video/webm" />
            </video>
          </div>

          {/* Actions */}
          <div className="flex gap-3 p-4">
            <a
              href={exportedBlobUrl}
              download={`clip_${exportClipIndex + 1}.${exportedExt}`}
              className="flex-1 flex items-center justify-center gap-2 py-3 bg-foreground text-background font-semibold rounded-xl hover:bg-foreground/90 transition-colors text-sm"
            >
              <Download className="w-4 h-4" /> Download
            </a>
            <button
              onClick={async () => {
                if (exportedBlob && exportClipIdRef.current != null) {
                  setUploadingExport(true);
                  try {
                    await uploadAudioClipVideo(exportClipIdRef.current, exportedBlob, "webm");
                  } catch (err: any) {
                    alert("Upload failed: " + (err?.response?.data?.detail || err?.message || "unknown"));
                    setUploadingExport(false);
                    return;
                  }
                  setUploadingExport(false);
                }
                setExportedBlobUrl(null);
                setExportedBlob(null);
                setStep(3);
              }}
              disabled={uploadingExport}
              className="flex-1 flex items-center justify-center gap-2 py-3 border border-border text-foreground font-semibold rounded-xl hover:bg-muted transition-colors text-sm disabled:opacity-50"
            >
              {uploadingExport
                ? <><Loader2 className="w-4 h-4 animate-spin" /> Uploading…</>
                : <><MonitorPlay className="w-4 h-4" /> Assign to Variation</>}
            </button>
          </div>

        </div>
      </div>
    )}
    </>
  );
}
