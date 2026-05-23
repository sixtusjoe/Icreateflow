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
  { id: "minimal", label: "Minimal", description: "Dark + neon-green", colors: ["#0a0a0f", "#00ffaa"] },
  { id: "vivid",   label: "Vivid",   description: "Purple + hot-pink", colors: ["#120028", "#ff5ac8"] },
  { id: "neon",    label: "Neon",    description: "Navy + cyan glow",  colors: ["#000814", "#00dcff"] },
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

  // Configure state — per clip template + bg
  const [clipConfigs, setClipConfigs] = useState<Record<number, { template_id: string; bg_path?: string }>>({});
  const [generating, setGenerating] = useState<Record<number, boolean>>({});
  const [generationErrors, setGenerationErrors] = useState<Record<number, string>>({});

  // Review state — per clip words being edited
  const [clipWords, setClipWords] = useState<Record<number, AudioWord[]>>({});
  const [editingClipId, setEditingClipId] = useState<number | null>(null);
  const [savingLyrics, setSavingLyrics] = useState(false);
  const [activeReviewClip, setActiveReviewClip] = useState(0);
  const videoRef = useRef<HTMLVideoElement>(null);

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
      await generateAudioVideoClip(clipId, cfg.template_id, cfg.bg_path);
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

  // ── Lyrics editing ────────────────────────────────────────────────────────

  const handleWordChange = (clipId: number, wordIndex: number, field: keyof AudioWord, value: string | number) => {
    setClipWords((cw) => {
      const updated = [...(cw[clipId] ?? [])];
      updated[wordIndex] = { ...updated[wordIndex], [field]: value };
      return { ...cw, [clipId]: updated };
    });
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
                            {t.colors.map((c) => (
                              <div key={c} className="h-4 w-4 rounded-full" style={{ background: c }} />
                            ))}
                          </div>
                          <div>
                            <p className="text-xs font-semibold">{t.label}</p>
                            <p className="text-xs text-muted-foreground">{t.description}</p>
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

        {/* ── Step 2: Review & Edit ────────────────────────────────────────── */}
        {step === 2 && track && (
          <div className="space-y-4">

            {/* Clip tabs */}
            <div className="flex gap-1 overflow-x-auto border-b border-border">
              {track.clips.map((clip, i) => (
                <button
                  key={clip.id}
                  onClick={() => { setActiveReviewClip(i); setEditingClipId(clip.id); }}
                  className={`shrink-0 border-b-2 px-4 py-2.5 text-sm font-medium transition-colors ${
                    activeReviewClip === i ? "border-lime text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"
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
              <div className="grid gap-4 lg:grid-cols-2">

                {/* Video preview */}
                <div className="space-y-3">
                  <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">Preview</p>
                  {activeClip.video?.status === "done" && activeClip.video.video_path ? (
                    <>
                      {/* 9:16 portrait container */}
                      <div className="flex justify-center">
                        <div
                          className="overflow-hidden rounded-xl border border-border bg-black w-full max-w-[280px]"
                          style={{ aspectRatio: "9/16" }}
                        >
                          <video
                            ref={videoRef}
                            key={activeClip.id}
                            src={fileUrl(activeClip.video.video_path)}
                            controls
                            className="w-full h-full object-cover"
                          />
                        </div>
                      </div>
                      {/* Download button */}
                      <a
                        href={fileUrl(activeClip.video.video_path)}
                        download={`clip_${activeClip.clip_index + 1}.mp4`}
                        className="flex w-full items-center justify-center gap-2 rounded-lg border border-border px-4 py-2.5 text-sm text-foreground hover:border-lime/50 hover:bg-muted transition-colors"
                      >
                        <Download className="h-4 w-4" />
                        Download MP4
                      </a>
                    </>
                  ) : activeClip.video?.status === "generating" || generating[activeClip.id] ? (
                    <div className="flex h-48 flex-col items-center justify-center gap-3 rounded-xl border border-border bg-card sm:h-64">
                      <Loader2 className="h-8 w-8 animate-spin text-lime" />
                      <p className="text-sm text-muted-foreground">Generating video…</p>
                    </div>
                  ) : activeClip.video?.status === "failed" ? (
                    <div className="flex h-48 flex-col items-center justify-center gap-3 rounded-xl border border-destructive/30 bg-destructive/5 sm:h-64">
                      <AlertCircle className="h-8 w-8 text-destructive" />
                      <p className="px-4 text-center text-sm text-destructive">{activeClip.video.error || "Generation failed"}</p>
                      <button
                        onClick={() => handleGenerateClip(activeClip.id)}
                        className="flex items-center gap-1.5 rounded-lg border border-lime/40 px-3 py-1.5 text-xs text-foreground"
                      >
                        <RefreshCw className="h-3.5 w-3.5" /> Retry
                      </button>
                    </div>
                  ) : (
                    <div className="flex h-48 flex-col items-center justify-center gap-3 rounded-xl border border-border bg-card sm:h-64">
                      <FileVideo className="h-8 w-8 text-muted-foreground/40" />
                      <p className="text-sm text-muted-foreground">No video yet</p>
                      <button
                        onClick={() => handleGenerateClip(activeClip.id)}
                        className="flex items-center gap-1.5 rounded-lg bg-lime px-3 py-1.5 text-xs font-medium text-black"
                      >
                        <Wand2 className="h-3.5 w-3.5" /> Generate
                      </button>
                    </div>
                  )}

                  <div className="rounded-xl border border-border bg-card px-3 py-2 text-xs text-muted-foreground">
                    <div className="flex items-center gap-2">
                      <Clock className="h-3.5 w-3.5 shrink-0" />
                      {formatTime(activeClip.start_s)} – {formatTime(activeClip.end_s)}
                    </div>
                  </div>
                </div>

                {/* Lyrics editor */}
                <div className="space-y-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">Lyrics / Words</p>
                    <div className="flex gap-2">
                      <button
                        onClick={() => handleSaveLyrics(activeClip.id)}
                        disabled={savingLyrics}
                        className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs font-medium hover:border-lime/50"
                      >
                        {savingLyrics ? <Loader2 className="h-3 w-3 animate-spin" /> : "Save"}
                      </button>
                      <button
                        onClick={() => handleSaveLyrics(activeClip.id).then(() => handleGenerateClip(activeClip.id))}
                        disabled={savingLyrics || generating[activeClip.id]}
                        className="flex items-center gap-1.5 rounded-lg bg-lime px-3 py-1.5 text-xs font-medium text-black disabled:opacity-50"
                      >
                        <RefreshCw className="h-3 w-3" />
                        <span className="hidden xs:inline">Save & </span>Regenerate
                      </button>
                    </div>
                  </div>

                  <div className="max-h-80 overflow-y-auto rounded-xl border border-border bg-card sm:max-h-[420px]">
                    {(clipWords[activeClip.id] ?? activeClip.words).length === 0 ? (
                      <div className="p-6 text-center text-sm text-muted-foreground">No words transcribed for this clip</div>
                    ) : (
                      <table className="w-full text-xs">
                        <thead className="sticky top-0 border-b border-border bg-card">
                          <tr>
                            <th className="px-3 py-2 text-left font-medium text-muted-foreground">Word</th>
                            <th className="px-2 py-2 text-right font-medium text-muted-foreground">Start</th>
                            <th className="px-2 py-2 text-right font-medium text-muted-foreground">End</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(clipWords[activeClip.id] ?? activeClip.words).map((w, wi) => (
                            <tr key={wi} className="border-b border-border/50 hover:bg-muted/30">
                              <td className="px-3 py-1.5">
                                <input
                                  value={w.word}
                                  onChange={(e) => handleWordChange(activeClip.id, wi, "word", e.target.value)}
                                  className="w-full min-w-0 bg-transparent font-mono outline-none focus:text-lime"
                                />
                              </td>
                              <td className="px-2 py-1.5 text-right">
                                <input
                                  type="number" step="0.01" value={w.start_s.toFixed(2)}
                                  onChange={(e) => handleWordChange(activeClip.id, wi, "start_s", parseFloat(e.target.value) || 0)}
                                  className="w-14 bg-transparent text-right font-mono outline-none focus:text-lime"
                                />
                              </td>
                              <td className="px-2 py-1.5 text-right">
                                <input
                                  type="number" step="0.01" value={w.end_s.toFixed(2)}
                                  onChange={(e) => handleWordChange(activeClip.id, wi, "end_s", parseFloat(e.target.value) || 0)}
                                  className="w-14 bg-transparent text-right font-mono outline-none focus:text-lime"
                                />
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </div>
                </div>
              </div>
            )}

            <div className="flex items-center justify-between pt-1">
              <button onClick={() => setStep(1)} className="flex items-center gap-2 rounded-lg border border-border px-4 py-2.5 text-sm">
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
        )}

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
