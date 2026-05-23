"use client";

import { useEffect, useRef, useState, useCallback } from "react";
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
} from "@/lib/api";
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
  Monitor,
  ImageIcon,
  CirclePlus,
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
  const [uploadingAsset, setUploadingAsset] = useState<Record<number, boolean>>({});

  // Review state — per clip words being edited
  const [clipWords, setClipWords] = useState<Record<number, AudioWord[]>>({});
  const [editingClipId, setEditingClipId] = useState<number | null>(null);
  const [savingLyrics, setSavingLyrics] = useState(false);
  const [activeReviewClip, setActiveReviewClip] = useState(0);
  const [isPreviewPaused, setIsPreviewPaused] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const bgInputRef = useRef<HTMLInputElement>(null);
  const coverInputRef = useRef<HTMLInputElement>(null);

  // Assign state
  const [assignedClips, setAssignedClips] = useState<Record<number, { variationId: number; variationName: string } | null>>({});
  const [assigning, setAssigning] = useState<Record<number, boolean>>({});

  // Confirm modal state
  const [confirmModal, setConfirmModal] = useState<{
    title: string;
    message: string;
    onConfirm: () => void;
  } | null>(null);

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
      const configs: Record<number, { template_id: string }> = {};
      const words: Record<number, AudioWord[]> = {};
      // trackData.clips don't carry per-clip words; distribute from the flat
      // trackData.words array (each word has a clip_index field from the DB).
      for (const clip of trackData.clips) {
        configs[clip.id] = { template_id: clip.video?.template_id ?? "minimal" };
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
      const configs: Record<number, { template_id: string }> = {};
      const words: Record<number, AudioWord[]> = {};
      // Distribute flat trackData.words to each clip by clip_index
      for (const clip of trackData.clips) {
        configs[clip.id] = { template_id: "minimal" };
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
        if (status !== "generating") setGenerating((g) => ({ ...g, [c.id]: false }));
      }
      setTrack((t) => t ? { ...t, clips: updatedClips.map((c) => ({ ...c, words: c.words ?? [] })) } : t);
      if (allDone && pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    }, 3000);
  }, [track]);

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

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
    setUploadingAsset((u) => ({ ...u, [clipId]: true }));
    try {
      const formData = new FormData();
      formData.append("file", file);
      const token = localStorage.getItem("token");
      const res = await fetch(
        `/api/audio-to-video/clips/${clipId}/upload-asset?asset_type=${assetType}`,
        { method: "POST", body: formData, headers: { Authorization: `Bearer ${token}` } },
      );
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      const key = assetType === "cover" ? "cover_path" : "bg_path";
      setClipConfigs((c) => ({
        ...c,
        [clipId]: { ...(c[clipId] ?? { template_id: "minimal" }), [key]: data.path },
      }));
    } catch (err: any) {
      alert("Upload failed: " + err.message);
    } finally {
      setUploadingAsset((u) => ({ ...u, [clipId]: false }));
    }
  };

  // ── Assign to variation ───────────────────────────────────────────────────

  const handleAssign = async (clipId: number, variationId: number, variationName: string) => {
    setAssigning((a) => ({ ...a, [clipId]: true }));
    try {
      await assignAudioClip(clipId, variationId);
      setAssignedClips((ac) => ({ ...ac, [clipId]: { variationId, variationName } }));
    } catch (err: any) {
      alert(err?.response?.data?.detail || "Failed to assign clip");
    } finally {
      setAssigning((a) => ({ ...a, [clipId]: false }));
    }
  };

  const activeClip = track?.clips.find((c) => c.id === editingClipId) ?? track?.clips[0] ?? null;

  // ─── Render ───────────────────────────────────────────────────────────────

  return (
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
          <Music2 className="h-5 w-5 shrink-0 text-lime" />
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
                    ? "bg-lime text-black"
                    : i < step
                    ? "bg-lime/30 text-lime cursor-pointer"
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
      <div className="mx-auto max-w-4xl px-4 py-6 sm:px-6 sm:py-8">

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
                        ? "border-lime bg-lime/10 text-foreground"
                        : "border-border bg-card hover:border-lime/50"
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
                    <FolderOpen className="h-4 w-4 text-lime" />
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
                          className="flex items-center gap-1.5 rounded-lg bg-lime px-3 py-1.5 text-xs font-medium text-black disabled:opacity-50"
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
                isDragging ? "border-lime bg-lime/5"
                : audioFile ? "border-green-500/60 bg-green-500/5"
                : "border-border bg-card hover:border-lime/50"
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
                    <Upload className="absolute -bottom-1 -right-1 h-5 w-5 text-lime sm:h-6 sm:w-6" />
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
                className="w-full rounded-lg border border-border bg-card px-4 py-2.5 text-sm outline-none focus:border-lime"
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
                      clipCount === n ? "border-lime bg-lime/10 text-foreground" : "border-border bg-card hover:border-lime/50"
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
              className="w-full rounded-xl bg-lime py-3 font-semibold text-black transition-opacity disabled:opacity-50"
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
                  className="flex w-full items-center justify-center gap-2 rounded-lg bg-lime px-4 py-2.5 text-sm font-medium text-black sm:w-auto"
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
                          className="flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-xs text-muted-foreground hover:border-lime/50 hover:text-foreground transition-colors"
                        >
                          <Download className="h-3.5 w-3.5" /> Download
                        </a>
                      )}
                      {videoStatus === "done" && <span className="flex items-center gap-1 text-xs text-green-500"><CheckCircle2 className="h-3.5 w-3.5" /> Done</span>}
                      {videoStatus === "failed" && <span className="flex items-center gap-1 text-xs text-destructive"><AlertCircle className="h-3.5 w-3.5" /> Failed</span>}
                      <button
                        onClick={() => handleGenerateClip(clip.id)}
                        disabled={isGenerating}
                        className="flex items-center gap-1.5 rounded-lg border border-lime/40 bg-lime/10 px-3 py-1.5 text-xs font-medium text-lime transition-colors hover:bg-lime/20 disabled:opacity-50"
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
                            cfg.template_id === t.id ? "border-lime ring-1 ring-lime" : "border-border hover:border-lime/50"
                          }`}
                        >
                          <div className="flex gap-1.5 sm:mb-2">
                            <div className="h-4 w-4 rounded-full" style={{ background: t.dot }} />
                          </div>
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
                className="flex items-center gap-2 rounded-lg bg-lime px-4 py-2.5 text-sm font-medium text-black"
              >
                Review & Edit <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}

        {/* ── Step 2: Overlay Studio ──────────────────────────────────────── */}
        {step === 2 && track && (() => {
          const cfg        = clipConfigs[activeClip?.id ?? -1] ?? { template_id: "minimal" };
          const lyricsText = activeClip ? getLyricsText(activeClip.id) : "";
          const lineCount  = lyricsText.split("\n").filter(Boolean).length;
          const isGen      = !!(activeClip && (generating[activeClip.id] || activeClip.video?.status === "generating"));

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
                        ? "border-lime text-foreground"
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
                /* ── Main layout: Studio LEFT · Phone Preview RIGHT ── */
                <div className="flex flex-col gap-4 lg:flex-row lg:items-start">

                  {/* ══ LEFT: Overlay Studio ══════════════════════════════════ */}
                  <div className="lg:w-[380px] shrink-0 rounded-2xl border border-border bg-card p-5 space-y-5">

                    {/* Header */}
                    <div>
                      <div className="flex items-center gap-2.5">
                        <Monitor className="h-5 w-5 text-foreground" />
                        <h2 className="text-lg font-bold">Overlay Studio</h2>
                      </div>
                      <p className="mt-0.5 text-sm text-muted-foreground">
                        Configure your cinematic music template.
                      </p>
                    </div>

                    {/* BG + Album Cover upload zones */}
                    <div className="grid grid-cols-2 gap-3">
                      {/* Hidden inputs */}
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

                      <div>
                        <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                          Background
                        </p>
                        <button
                          onClick={() => bgInputRef.current?.click()}
                          disabled={uploadingAsset[activeClip.id]}
                          className="w-full rounded-xl border-2 border-dashed border-border/50 bg-muted/20 px-3 py-4 flex flex-col items-center gap-1.5 hover:border-border transition-colors disabled:opacity-50"
                        >
                          {uploadingAsset[activeClip.id]
                            ? <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                            : <ImageIcon className="h-5 w-5 text-muted-foreground" />}
                          <span className="text-xs text-muted-foreground">
                            {cfg.bg_path ? "✓ BG set" : "Change BG"}
                          </span>
                        </button>
                      </div>

                      <div>
                        <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                          Album Cover
                        </p>
                        <button
                          onClick={() => coverInputRef.current?.click()}
                          disabled={uploadingAsset[activeClip.id]}
                          className="w-full rounded-xl border-2 border-dashed border-border/50 bg-muted/20 px-3 py-4 flex flex-col items-center gap-1.5 hover:border-border transition-colors disabled:opacity-50"
                        >
                          {uploadingAsset[activeClip.id]
                            ? <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                            : <CirclePlus className="h-5 w-5 text-muted-foreground" />}
                          <span className="text-xs text-muted-foreground">
                            {cfg.cover_path ? "✓ Cover set" : "Change Cover"}
                          </span>
                        </button>
                      </div>
                    </div>

                    {/* Lyrics Content textarea */}
                    <div>
                      <div className="mb-1.5 flex items-center justify-between">
                        <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                          Lyrics Content
                        </p>
                        <span className="text-xs text-muted-foreground">
                          {lineCount} {lineCount === 1 ? "Line" : "Lines"}
                        </span>
                      </div>
                      <textarea
                        value={lyricsText}
                        onChange={(e) =>
                          setClipLyricsText((lt) => ({ ...lt, [activeClip.id]: e.target.value }))
                        }
                        rows={6}
                        spellCheck={false}
                        className="w-full rounded-xl border border-border bg-background px-3.5 py-3 text-sm leading-relaxed resize-none outline-none focus:border-lime/60 transition-colors font-mono"
                        placeholder="Lyrics will appear here after transcription…"
                      />
                    </div>

                    {/* Design Variant — 2 × 2 grid */}
                    <div>
                      <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                        Design Variant
                      </p>
                      <div className="grid grid-cols-2 gap-2">
                        {TEMPLATES.map((tmpl) => {
                          const isActive = cfg.template_id === tmpl.id;
                          return (
                            <button
                              key={tmpl.id}
                              onClick={() =>
                                setClipConfigs((c) => ({
                                  ...c,
                                  [activeClip.id]: { ...cfg, template_id: tmpl.id },
                                }))
                              }
                              className={`flex items-center gap-2.5 rounded-xl border px-3.5 py-2.5 text-left transition-all ${
                                isActive
                                  ? "border-foreground/60 bg-muted/40"
                                  : "border-border/50 hover:border-border"
                              }`}
                            >
                              <div
                                className="h-3 w-3 shrink-0 rounded-full"
                                style={{ background: tmpl.dot }}
                              />
                              <span className="text-sm font-medium">{tmpl.label}</span>
                            </button>
                          );
                        })}
                      </div>
                    </div>

                    {generationErrors[activeClip.id] && (
                      <p className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
                        {generationErrors[activeClip.id]}
                      </p>
                    )}

                    {/* Action buttons */}
                    <div className="grid grid-cols-2 gap-3 pt-1">
                      {/* Pause / Play Preview */}
                      <button
                        onClick={() => {
                          if (!videoRef.current) return;
                          if (isPreviewPaused) {
                            videoRef.current.play();
                          } else {
                            videoRef.current.pause();
                          }
                          setIsPreviewPaused((p) => !p);
                        }}
                        disabled={activeClip.video?.status !== "done"}
                        className="flex items-center justify-center gap-2 rounded-xl border border-border bg-muted/30 px-4 py-2.5 text-sm font-medium hover:bg-muted/60 disabled:opacity-40 transition-colors"
                      >
                        {isPreviewPaused
                          ? <><Play className="h-4 w-4" /> Play Preview</>
                          : <><Pause className="h-4 w-4" /> Pause Preview</>}
                      </button>

                      {/* Export Frame */}
                      {activeClip.video?.status === "done" && activeClip.video.video_path ? (
                        <a
                          href={fileUrl(activeClip.video.video_path)}
                          download={`clip_${activeClip.clip_index + 1}.mp4`}
                          className="flex items-center justify-center gap-2 rounded-xl bg-foreground px-4 py-2.5 text-sm font-medium text-background hover:opacity-90 transition-opacity"
                        >
                          <Download className="h-4 w-4" /> Export Frame
                        </a>
                      ) : (
                        <button
                          onClick={() => handleSaveLyricsText(activeClip.id).then(() => handleGenerateClip(activeClip.id))}
                          disabled={isGen || savingLyrics}
                          className="flex items-center justify-center gap-2 rounded-xl bg-foreground px-4 py-2.5 text-sm font-medium text-background hover:opacity-90 disabled:opacity-40 transition-opacity"
                        >
                          {isGen
                            ? <><Loader2 className="h-4 w-4 animate-spin" /> Generating…</>
                            : <><Wand2 className="h-4 w-4" /> Generate</>}
                        </button>
                      )}
                    </div>

                    {/* Regenerate (if already done) */}
                    {activeClip.video?.status === "done" && (
                      <button
                        onClick={() => handleSaveLyricsText(activeClip.id).then(() => handleGenerateClip(activeClip.id))}
                        disabled={isGen || savingLyrics}
                        className="flex w-full items-center justify-center gap-2 rounded-xl border border-border py-2 text-sm text-muted-foreground hover:border-lime/40 hover:text-foreground disabled:opacity-40 transition-colors"
                      >
                        <RefreshCw className="h-3.5 w-3.5" />
                        Save lyrics &amp; Regenerate
                      </button>
                    )}
                  </div>

                  {/* ══ RIGHT: Phone preview ══════════════════════════════════ */}
                  <div className="flex flex-1 items-start justify-center pt-2">
                    <div className="w-full max-w-[300px]">
                      {/* Phone frame */}
                      <div className="relative rounded-[36px] border-[3px] border-border/60 bg-black overflow-hidden shadow-2xl"
                           style={{ aspectRatio: "9/16" }}>
                        {activeClip.video?.status === "done" && activeClip.video.video_path ? (
                          <video
                            ref={videoRef}
                            key={activeClip.id}
                            src={fileUrl(activeClip.video.video_path)}
                            controls
                            playsInline
                            autoPlay
                            loop
                            className="w-full h-full object-cover"
                          />
                        ) : isGen ? (
                          <div className="flex h-full flex-col items-center justify-center gap-3">
                            <Loader2 className="h-10 w-10 animate-spin text-lime" />
                            <p className="text-sm text-white/60">Generating…</p>
                          </div>
                        ) : activeClip.video?.status === "failed" ? (
                          <div className="flex h-full flex-col items-center justify-center gap-3 px-6">
                            <AlertCircle className="h-10 w-10 text-destructive" />
                            <p className="text-center text-xs text-white/60">
                              {activeClip.video.error || "Generation failed"}
                            </p>
                          </div>
                        ) : (
                          <div className="flex h-full flex-col items-center justify-center gap-3">
                            <FileVideo className="h-12 w-12 text-white/20" />
                            <p className="text-sm text-white/40">No video yet</p>
                          </div>
                        )}
                      </div>

                      {/* Below phone: timing info */}
                      <div className="mt-3 flex items-center justify-between px-1 text-xs text-muted-foreground">
                        <span className="flex items-center gap-1">
                          <Clock className="h-3.5 w-3.5" />
                          {formatTime(activeClip.start_s)} – {formatTime(activeClip.end_s)}
                        </span>
                        <span>{(activeClip.end_s - activeClip.start_s).toFixed(1)}s</span>
                      </div>
                    </div>
                  </div>

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
                  className="flex items-center gap-2 rounded-lg bg-lime px-4 py-2.5 text-sm font-medium text-black"
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
              const assigned = assignedClips[clip.id];

              return (
                <div key={clip.id} className="rounded-2xl border border-border bg-card p-4 sm:p-5">
                  <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <p className="font-semibold">Clip {clip.clip_index + 1}</p>
                      <p className="text-xs text-muted-foreground">{formatTime(clip.start_s)} – {formatTime(clip.end_s)}</p>
                    </div>
                    <div className="flex items-center gap-2">
                      {videoStatus === "done" && clip.video?.video_path && (
                        <a
                          href={fileUrl(clip.video.video_path)}
                          download={`clip_${clip.clip_index + 1}.mp4`}
                          className="flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1 text-xs text-muted-foreground hover:border-lime/50 hover:text-foreground transition-colors"
                        >
                          <Download className="h-3.5 w-3.5" /> Download
                        </a>
                      )}
                      {videoStatus !== "done" && !assigned && (
                        <span className="rounded-full border border-yellow-500/30 bg-yellow-500/10 px-2 py-0.5 text-xs text-yellow-500">
                          {videoStatus === "generating" ? "Generating…" : "No video yet"}
                        </span>
                      )}
                      {assigned && (
                        <span className="flex items-center gap-1 rounded-full border border-green-500/30 bg-green-500/10 px-2 py-0.5 text-xs text-green-500">
                          <CheckCircle2 className="h-3 w-3" /> {assigned.variationName}
                        </span>
                      )}
                    </div>
                  </div>

                  {videoStatus === "done" && !assigned && (
                    <div>
                      <p className="mb-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">Choose Variation</p>
                      <div className="flex flex-wrap gap-2">
                        {artistDetail?.variations?.map((v: any) => (
                          <button
                            key={v.id}
                            onClick={() => handleAssign(clip.id, v.id, v.name)}
                            disabled={assigning[clip.id]}
                            className="flex items-center gap-2 rounded-lg border border-border bg-background px-3 py-2 text-sm transition-colors hover:border-lime/50 hover:bg-lime/5 disabled:opacity-50"
                          >
                            {assigning[clip.id] ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <User className="h-3.5 w-3.5 text-muted-foreground" />}
                            {v.name}
                          </button>
                        ))}
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
                className="rounded-lg bg-lime px-4 py-2.5 text-sm font-medium text-black"
              >
                New Track
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
