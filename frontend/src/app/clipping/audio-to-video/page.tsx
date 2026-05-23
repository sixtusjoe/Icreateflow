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
  Play,
  RefreshCw,
  Trash2,
  User,
  Clock,
  FileVideo,
  Wand2,
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

// ─── Constants ────────────────────────────────────────────────────────────────

const TEMPLATES = [
  {
    id: "minimal",
    label: "Minimal",
    description: "Dark, clean, neon-green highlights",
    colors: ["#0a0a0f", "#00ffaa"],
  },
  {
    id: "vivid",
    label: "Vivid",
    description: "Deep purple with hot-pink accents",
    colors: ["#120028", "#ff5ac8"],
  },
  {
    id: "neon",
    label: "Neon",
    description: "Dark navy with electric cyan glow",
    colors: ["#000814", "#00dcff"],
  },
];

const STEPS = ["Upload", "Configure", "Review & Edit", "Assign"];

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

  // Configure state — per clip template + bg
  const [clipConfigs, setClipConfigs] = useState<
    Record<number, { template_id: string; bg_path?: string }>
  >({});
  const [generating, setGenerating] = useState<Record<number, boolean>>({});
  const [generationErrors, setGenerationErrors] = useState<Record<number, string>>({});

  // Review state — per clip words being edited
  const [clipWords, setClipWords] = useState<Record<number, AudioWord[]>>({});
  const [editingClipId, setEditingClipId] = useState<number | null>(null);
  const [savingLyrics, setSavingLyrics] = useState(false);
  const [activeReviewClip, setActiveReviewClip] = useState(0);
  const videoRef = useRef<HTMLVideoElement>(null);

  // Assign state
  const [assignedClips, setAssignedClips] = useState<
    Record<number, { variationId: number; variationName: string } | null>
  >({});
  const [assigning, setAssigning] = useState<Record<number, boolean>>({});
  const [assignSuccess, setAssignSuccess] = useState<Record<number, boolean>>({});

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
  }, [selectedArtistId]);

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
      // 1. Upload + Whisper
      const uploadResult = await uploadAudioTrack(
        selectedArtistId,
        audioFile,
        audioTitle || audioFile.name,
      );
      const trackId: number = uploadResult.track_id;

      // 2. Split into clips
      await splitAudioTrack(trackId, clipCount);

      // 3. Load full track data
      const trackData = await getAudioTrack(trackId);
      setTrack(trackData);

      // Init clip configs and words
      const configs: Record<number, { template_id: string }> = {};
      const words: Record<number, AudioWord[]> = {};
      for (const clip of trackData.clips) {
        configs[clip.id] = { template_id: "minimal" };
        words[clip.id] = clip.words ?? [];
      }
      setClipConfigs(configs);
      setClipWords(words);
      if (trackData.clips.length > 0) setEditingClipId(trackData.clips[0].id);

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
      setGenerationErrors((e) => ({
        ...e,
        [clipId]: err?.response?.data?.detail || err?.message || "Generation failed",
      }));
      setGenerating((g) => ({ ...g, [clipId]: false }));
    }
  };

  const handleGenerateAll = async () => {
    if (!track) return;
    for (const clip of track.clips) {
      await handleGenerateClip(clip.id);
    }
  };

  // Poll clip statuses until all done/failed
  const startPolling = useCallback(() => {
    if (pollRef.current) return;
    pollRef.current = setInterval(async () => {
      if (!track) return;
      let allDone = true;
      const updatedClips = await Promise.all(
        track.clips.map((c) => getAudioClip(c.id).catch(() => c)),
      );
      for (const c of updatedClips) {
        const status = c.video?.status;
        if (status === "generating" || status === "pending") allDone = false;
        if (status !== "generating") {
          setGenerating((g) => ({ ...g, [c.id]: false }));
        }
      }
      setTrack((t) =>
        t
          ? { ...t, clips: updatedClips.map((c) => ({ ...c, words: c.words ?? [] })) }
          : t,
      );
      if (allDone && pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    }, 3000);
  }, [track]);

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  // ── Lyrics editing ────────────────────────────────────────────────────────

  const handleWordChange = (
    clipId: number,
    wordIndex: number,
    field: keyof AudioWord,
    value: string | number,
  ) => {
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
      setAssignSuccess((s) => ({ ...s, [clipId]: true }));
    } catch (err: any) {
      alert(err?.response?.data?.detail || "Failed to assign clip");
    } finally {
      setAssigning((a) => ({ ...a, [clipId]: false }));
    }
  };

  // ─── Render helpers ────────────────────────────────────────────────────────

  const activeClip =
    track?.clips.find((c) => c.id === editingClipId) ?? track?.clips[0] ?? null;

  // ─── Steps ────────────────────────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* Header */}
      <div className="border-b border-border/40 px-6 py-4">
        <div className="flex items-center gap-3">
          <Music2 className="h-6 w-6 text-primary" />
          <h1 className="text-xl font-bold">Audio to Video</h1>
        </div>
        {/* Step dots */}
        <div className="mt-3 flex items-center gap-2">
          {STEPS.map((s, i) => (
            <div key={s} className="flex items-center gap-2">
              <button
                onClick={() => track && i <= step && setStep(i)}
                className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-bold transition-colors ${
                  i === step
                    ? "bg-primary text-primary-foreground"
                    : i < step
                    ? "bg-primary/30 text-primary cursor-pointer"
                    : "bg-muted text-muted-foreground cursor-default"
                }`}
              >
                {i < step ? <CheckCircle2 className="h-4 w-4" /> : i + 1}
              </button>
              <span
                className={`text-sm ${
                  i === step ? "font-medium text-foreground" : "text-muted-foreground"
                }`}
              >
                {s}
              </span>
              {i < STEPS.length - 1 && (
                <ChevronRight className="h-4 w-4 text-muted-foreground" />
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="mx-auto max-w-4xl px-6 py-8">
        {/* ── Step 0: Upload ───────────────────────────────────────────── */}
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
                    className={`rounded-lg border px-4 py-2 text-sm transition-colors ${
                      selectedArtistId === a.id
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-border bg-card hover:border-primary/50"
                    }`}
                  >
                    {a.name}
                  </button>
                ))}
              </div>
            </div>

            {/* Drop zone */}
            <div
              onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={handleFileDrop}
              onClick={() => fileInputRef.current?.click()}
              className={`cursor-pointer rounded-2xl border-2 border-dashed p-12 text-center transition-colors ${
                isDragging
                  ? "border-primary bg-primary/5"
                  : audioFile
                  ? "border-green-500/60 bg-green-500/5"
                  : "border-border bg-card hover:border-primary/50"
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
                <div className="flex flex-col items-center gap-3">
                  <CheckCircle2 className="h-12 w-12 text-green-500" />
                  <p className="text-lg font-medium">{audioFile.name}</p>
                  <p className="text-sm text-muted-foreground">
                    {(audioFile.size / 1024 / 1024).toFixed(2)} MB
                  </p>
                  <p className="text-xs text-muted-foreground">Click to change file</p>
                </div>
              ) : (
                <div className="flex flex-col items-center gap-4">
                  <div className="relative">
                    <Music2 className="h-16 w-16 text-muted-foreground/40" />
                    <Upload className="absolute -bottom-1 -right-1 h-6 w-6 text-primary" />
                  </div>
                  <div>
                    <p className="text-lg font-medium">Drop your audio file here</p>
                    <p className="mt-1 text-sm text-muted-foreground">
                      MP3, WAV, M4A, AAC, OGG, FLAC supported
                    </p>
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
                className="w-full rounded-lg border border-border bg-card px-4 py-2 text-sm outline-none focus:border-primary"
              />
            </div>

            {/* Clip count */}
            <div>
              <label className="mb-2 block text-sm font-medium">
                Number of Clips
              </label>
              <p className="mb-3 text-xs text-muted-foreground">
                The audio will be split into equal segments
              </p>
              <div className="flex gap-3">
                {([1, 3, 5] as const).map((n) => (
                  <button
                    key={n}
                    onClick={() => setClipCount(n)}
                    className={`flex-1 rounded-xl border py-4 text-center transition-colors ${
                      clipCount === n
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-border bg-card hover:border-primary/50"
                    }`}
                  >
                    <div className="text-2xl font-bold">{n}</div>
                    <div className="text-xs text-muted-foreground">
                      {n === 1 ? "clip" : "clips"}
                    </div>
                  </button>
                ))}
              </div>
            </div>

            {uploadError && (
              <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
                <AlertCircle className="h-4 w-4 shrink-0" />
                {uploadError}
              </div>
            )}

            <button
              onClick={handleUploadAndProcess}
              disabled={!audioFile || !selectedArtistId || uploading}
              className="w-full rounded-xl bg-primary py-3 font-semibold text-primary-foreground transition-opacity disabled:opacity-50"
            >
              {uploading ? (
                <span className="flex items-center justify-center gap-2">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Uploading & transcribing with Whisper…
                </span>
              ) : (
                "Process Audio →"
              )}
            </button>
          </div>
        )}

        {/* ── Step 1: Configure ──────────────────────────────────────────── */}
        {step === 1 && track && (
          <div className="space-y-6">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-lg font-bold">{track.title}</h2>
                <p className="text-sm text-muted-foreground">
                  {formatDuration(track.duration_s)} · {track.clips.length} clip
                  {track.clips.length !== 1 ? "s" : ""} · {track.words.length} words transcribed
                </p>
              </div>
              <button
                onClick={handleGenerateAll}
                className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"
              >
                <Wand2 className="h-4 w-4" />
                Generate All
              </button>
            </div>

            {track.clips.map((clip) => {
              const cfg = clipConfigs[clip.id] ?? { template_id: "minimal" };
              const videoStatus = clip.video?.status;
              const isGenerating = generating[clip.id] || videoStatus === "generating";

              return (
                <div key={clip.id} className="rounded-2xl border border-border bg-card p-5">
                  <div className="mb-4 flex items-center justify-between">
                    <div>
                      <p className="font-semibold">Clip {clip.clip_index + 1}</p>
                      <p className="text-xs text-muted-foreground">
                        {formatTime(clip.start_s)} – {formatTime(clip.end_s)} ·{" "}
                        {clip.words?.length ?? 0} words
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      {videoStatus === "done" && (
                        <span className="flex items-center gap-1 text-xs text-green-400">
                          <CheckCircle2 className="h-3.5 w-3.5" /> Done
                        </span>
                      )}
                      {videoStatus === "failed" && (
                        <span className="flex items-center gap-1 text-xs text-destructive">
                          <AlertCircle className="h-3.5 w-3.5" /> Failed
                        </span>
                      )}
                      <button
                        onClick={() => handleGenerateClip(clip.id)}
                        disabled={isGenerating}
                        className="flex items-center gap-1.5 rounded-lg border border-primary/40 bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary transition-colors hover:bg-primary/20 disabled:opacity-50"
                      >
                        {isGenerating ? (
                          <>
                            <Loader2 className="h-3.5 w-3.5 animate-spin" /> Generating…
                          </>
                        ) : (
                          <>
                            <Wand2 className="h-3.5 w-3.5" />
                            {videoStatus === "done" ? "Regenerate" : "Generate"}
                          </>
                        )}
                      </button>
                    </div>
                  </div>

                  {/* Template selector */}
                  <div className="mb-4">
                    <p className="mb-2 text-xs font-medium text-muted-foreground uppercase tracking-wider">
                      Template
                    </p>
                    <div className="flex gap-2">
                      {TEMPLATES.map((t) => (
                        <button
                          key={t.id}
                          onClick={() =>
                            setClipConfigs((c) => ({
                              ...c,
                              [clip.id]: { ...cfg, template_id: t.id },
                            }))
                          }
                          className={`flex-1 rounded-xl border p-3 text-left transition-all ${
                            cfg.template_id === t.id
                              ? "border-primary ring-1 ring-primary"
                              : "border-border hover:border-primary/50"
                          }`}
                        >
                          <div className="mb-2 flex gap-1.5">
                            {t.colors.map((c) => (
                              <div
                                key={c}
                                className="h-4 w-4 rounded-full"
                                style={{ background: c }}
                              />
                            ))}
                          </div>
                          <p className="text-xs font-semibold">{t.label}</p>
                          <p className="text-xs text-muted-foreground">{t.description}</p>
                        </button>
                      ))}
                    </div>
                  </div>

                  {generationErrors[clip.id] && (
                    <p className="mt-2 text-xs text-destructive">
                      {generationErrors[clip.id]}
                    </p>
                  )}
                </div>
              );
            })}

            <div className="flex justify-between pt-2">
              <button
                onClick={() => setStep(0)}
                className="flex items-center gap-2 rounded-lg border border-border px-4 py-2 text-sm"
              >
                <ChevronLeft className="h-4 w-4" /> Back
              </button>
              <button
                onClick={() => {
                  setActiveReviewClip(0);
                  setEditingClipId(track.clips[0]?.id ?? null);
                  setStep(2);
                }}
                className="flex items-center gap-2 rounded-lg bg-primary px-5 py-2 text-sm font-medium text-primary-foreground"
              >
                Review & Edit <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}

        {/* ── Step 2: Review & Edit ──────────────────────────────────────── */}
        {step === 2 && track && (
          <div className="space-y-4">
            {/* Clip tabs */}
            <div className="flex gap-2 border-b border-border pb-0">
              {track.clips.map((clip, i) => (
                <button
                  key={clip.id}
                  onClick={() => {
                    setActiveReviewClip(i);
                    setEditingClipId(clip.id);
                  }}
                  className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                    activeReviewClip === i
                      ? "border-primary text-primary"
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
              <div className="grid gap-4 lg:grid-cols-2">
                {/* Video preview */}
                <div className="space-y-3">
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                    Preview
                  </p>
                  {activeClip.video?.status === "done" && activeClip.video.video_path ? (
                    <div className="overflow-hidden rounded-xl border border-border bg-black">
                      <video
                        ref={videoRef}
                        key={activeClip.id}
                        src={`/files/${activeClip.video.video_path}`}
                        controls
                        className="w-full"
                        style={{ maxHeight: "500px", objectFit: "contain" }}
                      />
                    </div>
                  ) : activeClip.video?.status === "generating" || generating[activeClip.id] ? (
                    <div className="flex h-64 flex-col items-center justify-center gap-3 rounded-xl border border-border bg-card">
                      <Loader2 className="h-8 w-8 animate-spin text-primary" />
                      <p className="text-sm text-muted-foreground">Generating video…</p>
                    </div>
                  ) : activeClip.video?.status === "failed" ? (
                    <div className="flex h-64 flex-col items-center justify-center gap-3 rounded-xl border border-destructive/30 bg-destructive/5">
                      <AlertCircle className="h-8 w-8 text-destructive" />
                      <p className="text-sm text-destructive">
                        {activeClip.video.error || "Generation failed"}
                      </p>
                      <button
                        onClick={() => handleGenerateClip(activeClip.id)}
                        className="flex items-center gap-1.5 rounded-lg border border-primary/40 px-3 py-1.5 text-xs text-primary"
                      >
                        <RefreshCw className="h-3.5 w-3.5" /> Retry
                      </button>
                    </div>
                  ) : (
                    <div className="flex h-64 flex-col items-center justify-center gap-3 rounded-xl border border-border bg-card">
                      <FileVideo className="h-8 w-8 text-muted-foreground/40" />
                      <p className="text-sm text-muted-foreground">No video yet</p>
                      <button
                        onClick={() => handleGenerateClip(activeClip.id)}
                        className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground"
                      >
                        <Wand2 className="h-3.5 w-3.5" /> Generate
                      </button>
                    </div>
                  )}

                  {/* Clip info */}
                  <div className="rounded-xl border border-border bg-card p-3 text-xs text-muted-foreground">
                    <div className="flex items-center gap-3">
                      <Clock className="h-3.5 w-3.5" />
                      {formatTime(activeClip.start_s)} – {formatTime(activeClip.end_s)}
                    </div>
                  </div>
                </div>

                {/* Lyrics editor */}
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                      Lyrics / Words
                    </p>
                    <div className="flex gap-2">
                      <button
                        onClick={() => handleSaveLyrics(activeClip.id)}
                        disabled={savingLyrics}
                        className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs font-medium hover:border-primary/50"
                      >
                        {savingLyrics ? (
                          <Loader2 className="h-3 w-3 animate-spin" />
                        ) : (
                          "Save"
                        )}
                      </button>
                      <button
                        onClick={() => {
                          handleSaveLyrics(activeClip.id).then(() =>
                            handleGenerateClip(activeClip.id),
                          );
                        }}
                        disabled={savingLyrics || generating[activeClip.id]}
                        className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground disabled:opacity-50"
                      >
                        <RefreshCw className="h-3 w-3" /> Save & Regenerate
                      </button>
                    </div>
                  </div>

                  <div className="max-h-[420px] overflow-y-auto rounded-xl border border-border bg-card">
                    {(clipWords[activeClip.id] ?? activeClip.words).length === 0 ? (
                      <div className="p-6 text-center text-sm text-muted-foreground">
                        No words transcribed for this clip
                      </div>
                    ) : (
                      <table className="w-full text-xs">
                        <thead className="sticky top-0 border-b border-border bg-card">
                          <tr>
                            <th className="px-3 py-2 text-left font-medium text-muted-foreground">Word</th>
                            <th className="px-3 py-2 text-right font-medium text-muted-foreground">Start (s)</th>
                            <th className="px-3 py-2 text-right font-medium text-muted-foreground">End (s)</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(clipWords[activeClip.id] ?? activeClip.words).map((w, wi) => (
                            <tr key={wi} className="border-b border-border/50 hover:bg-muted/30">
                              <td className="px-3 py-1.5">
                                <input
                                  value={w.word}
                                  onChange={(e) =>
                                    handleWordChange(activeClip.id, wi, "word", e.target.value)
                                  }
                                  className="w-full bg-transparent font-mono outline-none focus:text-primary"
                                />
                              </td>
                              <td className="px-3 py-1.5 text-right">
                                <input
                                  type="number"
                                  step="0.01"
                                  value={w.start_s.toFixed(2)}
                                  onChange={(e) =>
                                    handleWordChange(
                                      activeClip.id,
                                      wi,
                                      "start_s",
                                      parseFloat(e.target.value) || 0,
                                    )
                                  }
                                  className="w-16 bg-transparent text-right font-mono outline-none focus:text-primary"
                                />
                              </td>
                              <td className="px-3 py-1.5 text-right">
                                <input
                                  type="number"
                                  step="0.01"
                                  value={w.end_s.toFixed(2)}
                                  onChange={(e) =>
                                    handleWordChange(
                                      activeClip.id,
                                      wi,
                                      "end_s",
                                      parseFloat(e.target.value) || 0,
                                    )
                                  }
                                  className="w-16 bg-transparent text-right font-mono outline-none focus:text-primary"
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

            <div className="flex justify-between pt-2">
              <button
                onClick={() => setStep(1)}
                className="flex items-center gap-2 rounded-lg border border-border px-4 py-2 text-sm"
              >
                <ChevronLeft className="h-4 w-4" /> Back
              </button>
              <button
                onClick={() => setStep(3)}
                className="flex items-center gap-2 rounded-lg bg-primary px-5 py-2 text-sm font-medium text-primary-foreground"
              >
                Assign to Variations <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}

        {/* ── Step 3: Assign ─────────────────────────────────────────────── */}
        {step === 3 && track && (
          <div className="space-y-6">
            <div>
              <h2 className="text-lg font-bold">Assign Clips to Variations</h2>
              <p className="text-sm text-muted-foreground">
                Assign each generated clip to an artist variation for scheduling
              </p>
            </div>

            {track.clips.map((clip) => {
              const videoStatus = clip.video?.status;
              const assigned = assignedClips[clip.id];

              return (
                <div key={clip.id} className="rounded-2xl border border-border bg-card p-5">
                  <div className="mb-4 flex items-start justify-between">
                    <div>
                      <p className="font-semibold">Clip {clip.clip_index + 1}</p>
                      <p className="text-xs text-muted-foreground">
                        {formatTime(clip.start_s)} – {formatTime(clip.end_s)}
                      </p>
                    </div>
                    {videoStatus !== "done" && (
                      <span className="rounded-full border border-yellow-500/30 bg-yellow-500/10 px-2 py-0.5 text-xs text-yellow-500">
                        {videoStatus === "generating" ? "Generating…" : "No video yet"}
                      </span>
                    )}
                    {assigned && (
                      <span className="flex items-center gap-1 rounded-full border border-green-500/30 bg-green-500/10 px-2 py-0.5 text-xs text-green-400">
                        <CheckCircle2 className="h-3 w-3" /> Assigned to {assigned.variationName}
                      </span>
                    )}
                  </div>

                  {videoStatus === "done" && !assigned && (
                    <div>
                      <p className="mb-2 text-xs font-medium text-muted-foreground uppercase tracking-wider">
                        Choose Variation
                      </p>
                      <div className="flex flex-wrap gap-2">
                        {artistDetail?.variations?.map((v: any) => (
                          <button
                            key={v.id}
                            onClick={() => handleAssign(clip.id, v.id, v.name)}
                            disabled={assigning[clip.id]}
                            className="flex items-center gap-2 rounded-lg border border-border bg-background px-3 py-2 text-sm transition-colors hover:border-primary/50 hover:bg-primary/5 disabled:opacity-50"
                          >
                            {assigning[clip.id] ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                              <User className="h-3.5 w-3.5 text-muted-foreground" />
                            )}
                            {v.name}
                          </button>
                        ))}
                        {!artistDetail?.variations?.length && (
                          <p className="text-sm text-muted-foreground">
                            No variations found for this artist
                          </p>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}

            <div className="flex justify-between pt-2">
              <button
                onClick={() => setStep(2)}
                className="flex items-center gap-2 rounded-lg border border-border px-4 py-2 text-sm"
              >
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
                  setAssignSuccess({});
                  setStep(0);
                }}
                className="rounded-lg bg-primary px-5 py-2 text-sm font-medium text-primary-foreground"
              >
                Start New Track
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
