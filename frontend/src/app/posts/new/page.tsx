"use client";

import React, { Suspense, useEffect, useState, useRef, useCallback } from "react";
import { createPortal } from "react-dom";
import { useSearchParams } from "next/navigation";
import { toast } from "sonner";
import {
  Link2, Upload, Wand2, Download, Play, Clock, Send, RefreshCw, Eye,
  Image as ImageIcon, Type, Sparkles, Check, Loader2, RotateCcw,
  AlertCircle, ChevronDown,
} from "lucide-react";
import {
  getBrands, importTikTokPost, uploadSlidesManually, getPost, updateSlide,
  uploadVariationImage, generateVariationImage, approveVariation,
  updateVariation, generatePost, getGenerationStatus,
  schedulePost, postNow, getMusicTracks, getDownloadUrl, downloadFile, fileUrl,
  rerunOcr, getOutputSlides, regenerateSlide, regenerateVideo, updatePostMusic,
  updateOutputTiktokSettings, getFailedOutputs, retryOutput, clearFailedOutputs,
} from "@/lib/api";
import { TikTokSettingsCard } from "@/components/TikTokSettingsCard";
import { PostingProgressModal } from "@/components/PostingProgressModal";

type Plat = "youtube" | "instagram" | "facebook";
const PLATFORMS: Plat[] = ["youtube", "instagram", "facebook"];
const PLAT_LABEL: Record<Plat, string> = { youtube: "YouTube", instagram: "Instagram", facebook: "Facebook" };

type Step = "import" | "edit" | "variations" | "generate";

// ── Failed Outputs Section ────────────────────────────────────────────────────
// Shows persisted per-platform posting errors for both manual Post Now and
// scheduled dispatch. Mirrors FailedPostsSection on the clipping side.
function FailedOutputsSection({
  postId,
  failedOutputs,
  setFailedOutputs,
}: {
  postId: number;
  failedOutputs: any[];
  setFailedOutputs: React.Dispatch<React.SetStateAction<any[]>>;
}) {
  const [open, setOpen] = React.useState(true);
  const [clearing, setClearing] = React.useState(false);
  const [retryingKey, setRetryingKey] = React.useState<string | null>(null);
  const [capRetry, setCapRetry] = React.useState<{ outputId: number; platform: string } | null>(null);
  const [capRetrying, setCapRetrying] = React.useState(false);

  const isCapError = (err?: string) =>
    !!(err && (err.toLowerCase().includes("reached_active_user_cap") || err.toLowerCase().includes("active_user_cap")));

  const handleClearAll = async () => {
    setClearing(true);
    try {
      await clearFailedOutputs(postId);
      setFailedOutputs([]);
      toast.success("Cleared all failed posts");
    } catch {
      toast.error("Could not clear");
    } finally {
      setClearing(false);
    }
  };

  const handleRetry = async (outputId: number, platform: string, mode: "normal" | "draft" | "delayed") => {
    const key = `${outputId}:${platform}`;
    setRetryingKey(key);
    if (mode !== "normal") setCapRetrying(true);
    try {
      await retryOutput(outputId, mode);
      if (mode === "delayed") {
        toast.success("TikTok retry scheduled in 6 hours");
      } else if (mode === "draft") {
        toast.success("Retry scheduled as draft — will post to TikTok inbox immediately");
      } else {
        toast.success("Retry submitted");
      }
      setCapRetry(null);
      // Remove the retried platform from the failed list
      setFailedOutputs((prev) =>
        prev
          .map((o) => {
            if (o.output_id !== outputId) return o;
            const platforms = { ...o.platforms };
            delete platforms[platform];
            return { ...o, platforms };
          })
          .filter((o) => Object.keys(o.platforms).length > 0)
      );
    } catch {
      toast.error("Failed to retry");
    } finally {
      setRetryingKey(null);
      setCapRetrying(false);
    }
  };

  if (failedOutputs.length === 0) return null;

  // Flatten to a list of {outputId, accountName, platform, error, friendlyError}
  const rows = failedOutputs.flatMap((o: any) =>
    Object.entries(o.platforms).map(([plat, pd]: [string, any]) => ({
      outputId: o.output_id,
      accountName: o.account_name,
      platform: plat,
      error: pd.error,
      friendlyError: pd.friendly_error || pd.error,
    }))
  );

  return (
    <>
      {/* TikTok cap-error retry popup */}
      {capRetry && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-sm rounded-2xl bg-background p-6 shadow-xl">
            <h3 className="text-base font-semibold">Retry TikTok post</h3>
            <p className="mt-2 text-sm text-muted-foreground">
              This account has hit TikTok's active user cap. Choose how to retry:
            </p>
            <div className="mt-5 flex flex-col gap-2.5">
              <button
                onClick={() => handleRetry(capRetry.outputId, capRetry.platform, "draft")}
                disabled={capRetrying}
                className="flex flex-col items-start gap-0.5 rounded-xl border border-border bg-muted/40 px-4 py-3 text-left transition-colors hover:bg-muted disabled:opacity-50"
              >
                <span className="text-sm font-medium">Post as draft</span>
                <span className="text-xs text-muted-foreground">Posts immediately to TikTok inbox — you publish from the app</span>
              </button>
              <button
                onClick={() => handleRetry(capRetry.outputId, capRetry.platform, "delayed")}
                disabled={capRetrying}
                className="flex flex-col items-start gap-0.5 rounded-xl border border-border bg-muted/40 px-4 py-3 text-left transition-colors hover:bg-muted disabled:opacity-50"
              >
                <span className="text-sm font-medium">Retry in 6 hours</span>
                <span className="text-xs text-muted-foreground">System retries direct post after the cap cooldown</span>
              </button>
              <button
                onClick={() => setCapRetry(null)}
                disabled={capRetrying}
                className="mt-1 text-sm text-muted-foreground hover:text-foreground disabled:opacity-50"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      <section className="rounded-2xl border border-destructive/30 bg-destructive/5 overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-3 md:px-5">
          <button
            onClick={() => setOpen((o) => !o)}
            className="flex items-center gap-2 flex-1 text-left"
          >
            <AlertCircle className="h-4 w-4 text-destructive shrink-0" />
            <span className="text-sm font-semibold text-destructive whitespace-nowrap">Failed Posts</span>
            <span className="rounded-full bg-destructive/15 px-2 py-0.5 text-xs font-semibold text-destructive shrink-0">
              {rows.length}
            </span>
            <ChevronDown className={`h-4 w-4 text-destructive/60 ml-1 shrink-0 transition-transform ${open ? "rotate-180" : ""}`} />
          </button>
          <button
            onClick={handleClearAll}
            disabled={clearing}
            className="shrink-0 text-xs text-destructive/70 hover:text-destructive font-medium disabled:opacity-50"
          >
            {clearing ? "Clearing…" : "Clear all"}
          </button>
        </div>
        {open && (
          <div className="divide-y divide-destructive/10 border-t border-destructive/20">
            {rows.map((row, idx) => {
              const key = `${row.outputId}:${row.platform}`;
              const isRetrying = retryingKey === key;
              return (
                <div key={idx} className="flex flex-col gap-1.5 px-4 py-3 md:px-5 sm:flex-row sm:items-center sm:gap-3">
                  {/* Mobile: platform + account + retry button */}
                  <div className="flex items-center gap-2 sm:contents">
                    <span className="shrink-0 rounded-md bg-muted px-2 py-0.5 text-xs font-semibold capitalize">
                      {row.platform}
                    </span>
                    <span className="text-xs text-muted-foreground shrink-0 flex-1 sm:flex-none truncate">
                      {row.accountName}
                    </span>
                    <button
                      onClick={() =>
                        isCapError(row.error) && row.platform === "tiktok"
                          ? setCapRetry({ outputId: row.outputId, platform: row.platform })
                          : handleRetry(row.outputId, row.platform, "normal")
                      }
                      disabled={isRetrying}
                      className="sm:hidden ml-auto shrink-0 inline-flex items-center gap-1.5 rounded-lg border border-border bg-background px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted disabled:opacity-50"
                    >
                      {isRetrying ? <Loader2 className="h-3 w-3 animate-spin" /> : <RotateCcw className="h-3 w-3" />}
                      {isRetrying ? "Retrying…" : "Retry"}
                    </button>
                  </div>
                  {/* Error message */}
                  <span className="text-xs text-destructive/90 sm:flex-1 sm:min-w-0 sm:truncate" title={row.friendlyError}>
                    {row.friendlyError}
                  </span>
                  {/* Retry on desktop */}
                  <button
                    onClick={() =>
                      isCapError(row.error) && row.platform === "tiktok"
                        ? setCapRetry({ outputId: row.outputId, platform: row.platform })
                        : handleRetry(row.outputId, row.platform, "normal")
                    }
                    disabled={isRetrying}
                    className="hidden sm:inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-border bg-background px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted disabled:opacity-50"
                  >
                    {isRetrying ? <Loader2 className="h-3 w-3 animate-spin" /> : <RotateCcw className="h-3 w-3" />}
                    {isRetrying ? "Retrying…" : "Retry"}
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </section>
    </>
  );
}

export default function NewPostPage() {
  return (
    <Suspense fallback={<div className="p-8 text-muted-foreground">Loading...</div>}>
      <NewPostPageInner />
    </Suspense>
  );
}

function NewPostPageInner() {
  const searchParams = useSearchParams();
  const editId = searchParams.get("edit");

  const [step, setStep] = useState<Step>("import");
  const [brands, setBrands] = useState<any[]>([]);
  const [musicTracks, setMusicTracks] = useState<any[]>([]);

  const [importMode, setImportMode] = useState<"tiktok" | "upload">("upload");
  const [selectedBrand, setSelectedBrand] = useState<number | null>(null);
  const [tiktokUrl, setTiktokUrl] = useState("");
  const [postNumber] = useState(1); // kept for compatibility; server auto-assigns now
  const [importing, setImporting] = useState(false);
  const [manualFiles, setManualFiles] = useState<File[]>([]);
  const [manualCaption, setManualCaption] = useState("");

  const [post, setPost] = useState<any>(null);
  const [generating, setGenerating] = useState(false);
  const [genProgress, setGenProgress] = useState(0);
  const [scheduleTime, setScheduleTime] = useState("");
  const [selectedMusic, setSelectedMusic] = useState<number | null>(null);
  const [platMusic, setPlatMusic] = useState<Record<Plat, number | null>>({ youtube: null, instagram: null, facebook: null });
  const [platMusicLib, setPlatMusicLib] = useState<Record<Plat, any[]>>({ youtube: [], instagram: [], facebook: [] });
  // Per-output TikTok-settings validity. Tracks each non-master, TikTok-
  // connected variation; Post Now / Save Schedule are disabled while any
  // entry is false. The cards report up via onValidityChange.
  const [tiktokValid, setTiktokValid] = useState<Record<number, boolean>>({});
  const onTiktokValidity = useCallback((outputId: number, valid: boolean) => {
    setTiktokValid((prev) => (prev[outputId] === valid ? prev : { ...prev, [outputId]: valid }));
  }, []);
  const allTiktokValid = Object.values(tiktokValid).every(Boolean);
  const [previewPlatform, setPreviewPlatform] = useState<Plat>("youtube");
  const [regeneratingPlatform, setRegeneratingPlatform] = useState<string | null>(null);
  const [postingModalOpen, setPostingModalOpen] = useState(false);
  const [postingResults, setPostingResults] = useState<any[] | null>(null);
  const [failedOutputs, setFailedOutputs] = useState<any[]>([]);
  const [editLoaded, setEditLoaded] = useState(false);
  const [expandedImage, setExpandedImage] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<number>(0);
  const slideTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  // Debounce timer for the post-level caption textarea on Edit Slides
  // step. Without this, edits live only in local state and are lost when
  // advancing to Generate.
  const captionTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [outputSlides, setOutputSlides] = useState<any[]>([]);
  const [previewTab, setPreviewTab] = useState<number>(0);
  const [rerunningOcr, setRerunningOcr] = useState(false);
  const [downloading, setDownloading] = useState<string | null>(null);
  const [editingSlide, setEditingSlide] = useState<{
    accountId: number; slideNumber: number; slideType: string;
    titleText: string; bodyText: string; ctaText: string;
    fontSizeTitle: number; fontSizeBody: number; fontSizeCta: number;
    yRatioTitle: number; yRatioBody: number; yRatioCta: number;
    xRatioTitle: number; xRatioBody: number; xRatioCta: number;
    scaleTitle: number; scaleBody: number; scaleCta: number;
    fontWeight: string; textStyle: string;
    sourceImagePath: string;
  } | null>(null);
  const [regenerating, setRegenerating] = useState(false);
  const [regeneratingVideo, setRegeneratingVideo] = useState<number | null>(null);
  const [cacheKey, setCacheKey] = useState(0);

  useEffect(() => {
    getBrands().then(setBrands).catch(() => {});
    getMusicTracks().then(setMusicTracks).catch(() => {});
    PLATFORMS.forEach((p) => {
      getMusicTracks(p).then((ts) => setPlatMusicLib((prev) => ({ ...prev, [p]: ts }))).catch(() => {});
    });
  }, []);

  useEffect(() => {
    if (editId && !editLoaded) {
      setEditLoaded(true);
      getPost(Number(editId))
        .then((data) => {
          setPost(data);
          setSelectedBrand(data.brand_id);
          if (data.scheduled_time) setScheduleTime(data.scheduled_time);
          if (data.music_track_id) setSelectedMusic(data.music_track_id);
          setPlatMusic({
            youtube: data.youtube_music_track_id || null,
            instagram: data.instagram_music_track_id || null,
            facebook: data.facebook_music_track_id || null,
          });
          // Auto-jump to Generate tab if content is already generated
          if (data.outputs && data.outputs.length > 0) {
            setStep("generate");
          } else {
            setStep("edit");
          }
          toast.success("Post loaded");
          // Load any persisted platform failures for this post
          getFailedOutputs(Number(editId))
            .then((fo) => setFailedOutputs(fo || []))
            .catch(() => {});
        })
        .catch(() => toast.error("Failed to load post"));
    }
  }, [editId, editLoaded]);

  const selectedBrandData = brands.find((b: any) => b.id === selectedBrand);

  const handleImport = async () => {
    if (!selectedBrand) return toast.error("Select a brand first");
    if (!tiktokUrl) return toast.error("Paste a TikTok URL");
    setImporting(true);
    try {
      const result = await importTikTokPost({ tiktok_url: tiktokUrl, brand_id: selectedBrand });
      setPost(result);
      setStep("edit");
      toast.success(`Imported ${result.slides?.length || 0} slides`);
    } catch (e: any) {
      toast.error("Import failed: " + (e.response?.data?.detail || e.message));
    } finally { setImporting(false); }
  };

  const handleManualUpload = async () => {
    if (!selectedBrand) return toast.error("Select a brand first");
    if (manualFiles.length === 0) return toast.error("Upload at least one slide image");
    setImporting(true);
    try {
      const result = await uploadSlidesManually(selectedBrand, manualCaption, manualFiles);
      setPost(result);
      setStep("edit");
      toast.success(`Uploaded ${result.slides?.length || 0} slides`);
    } catch (e: any) {
      toast.error("Upload failed: " + (e.response?.data?.detail || e.message));
    } finally { setImporting(false); }
  };

  const reloadPost = async () => {
    if (!post?.id) return;
    const updated = await getPost(post.id);
    setPost(updated);
  };

  // Persist post-level caption edits. Debounced 500ms while typing;
  // `flush` parameter skips the debounce so we can force a save before
  // advancing to the Generate step.
  const handleCaptionChange = useCallback((value: string, flush = false) => {
    if (!post) return;
    setPost((prev: any) => (prev ? { ...prev, caption: value } : prev));
    if (captionTimer.current) clearTimeout(captionTimer.current);
    const save = async () => {
      try { await schedulePost(post.id, { caption: value }); }
      catch { toast.error("Failed to save caption"); }
    };
    if (flush) { save(); return; }
    captionTimer.current = setTimeout(save, 500);
  }, [post]);

  const handleSlideUpdate = useCallback((slideNum: number, field: string, value: string | boolean) => {
    if (!post) return;
    // Update local state immediately (no cursor jump)
    setPost((prev: any) => {
      if (!prev) return prev;
      const updatedSlides = prev.slides.map((s: any) =>
        s.slide_number === slideNum ? { ...s, [field]: value } : s
      );
      return { ...prev, slides: updatedSlides };
    });
    // Debounce the API call (save after 500ms of no typing)
    const key = `${slideNum}-${field}`;
    if (slideTimers.current[key]) clearTimeout(slideTimers.current[key]);
    slideTimers.current[key] = setTimeout(async () => {
      try { await updateSlide(post.id, slideNum, { [field]: value }); }
      catch { toast.error("Failed to update slide"); }
    }, 500);
  }, [post]);

  const handleUploadVariation = async (variationId: number, file: File) => {
    try { await uploadVariationImage(variationId, file); await reloadPost(); toast.success("Image uploaded"); }
    catch { toast.error("Upload failed"); }
  };

  const handleGenerateAI = async (variationId: number) => {
    const prompt = window.prompt("Describe the image to generate:");
    if (!prompt) return;
    try {
      toast.info("Generating image...");
      await generateVariationImage(variationId, prompt);
      await reloadPost();
      toast.success("Image generated! Review and approve it.");
    } catch (e: any) {
      toast.error("Generation failed: " + (e.response?.data?.detail || e.message));
    }
  };

  const handleApprove = async (variationId: number) => {
    try { await approveVariation(variationId); await reloadPost(); toast.success("Approved"); }
    catch { toast.error("Failed"); }
  };

  const handleKeep = async (variationId: number) => {
    try { await updateVariation(variationId, "keep"); await reloadPost(); }
    catch { toast.error("Failed"); }
  };

  const handleGenerate = async () => {
    if (!post) return;
    setGenerating(true);
    setGenProgress(10);
    try {
      await generatePost(post.id);
      const poll = setInterval(async () => {
        const status = await getGenerationStatus(post.id);
        if (status.status === "done") {
          clearInterval(poll); setGenProgress(100); setGenerating(false);
          await reloadPost(); toast.success("All slides and videos generated!");
        } else if (status.status === "error") {
          clearInterval(poll); setGenerating(false);
          toast.error("Generation failed: " + status.error);
        } else { setGenProgress((p) => Math.min(p + 10, 90)); }
      }, 2000);
    } catch { setGenerating(false); toast.error("Generation failed"); }
  };

  const handleSchedule = async () => {
    if (!post) return;
    try {
      await schedulePost(post.id, { scheduled_time: scheduleTime, music_track_id: selectedMusic || undefined });
      await updatePostMusic(post.id, {
        youtube_music_track_id: platMusic.youtube ?? null,
        instagram_music_track_id: platMusic.instagram ?? null,
        facebook_music_track_id: platMusic.facebook ?? null,
      });
      toast.success("Post scheduled!");
    } catch { toast.error("Failed to schedule"); }
  };

  const handleRegeneratePlatformVideo = async (accountId: number, platform: Plat) => {
    if (!post) return;
    const key = `${accountId}:${platform}`;
    setRegeneratingPlatform(key);
    try {
      await regenerateVideo(post.id, accountId, platform);
      await loadOutputSlides();
      await reloadPost();
      setCacheKey(Date.now());
      toast.success(`${PLAT_LABEL[platform]} video regenerated`);
    } catch (e: any) {
      toast.error("Regeneration failed: " + (e.response?.data?.detail || e.message));
    } finally { setRegeneratingPlatform(null); }
  };

  const handleRerunOcr = async () => {
    if (!post) return;
    setRerunningOcr(true);
    try {
      const result = await rerunOcr(post.id);
      await reloadPost();
      if (result.extracted_any) {
        toast.success(`OCR complete — text pulled from ${result.updated} slides`);
      } else {
        toast.warning("OCR ran, but no overlay text was detected. Check that your Anthropic key is valid and the slides actually have overlay text.");
      }
    } catch (e: any) {
      toast.error("OCR failed: " + (e.response?.data?.detail || e.message));
    } finally { setRerunningOcr(false); }
  };

  const loadOutputSlides = async () => {
    if (!post) return;
    try {
      const data = await getOutputSlides(post.id);
      setOutputSlides(data);
    } catch { /* no outputs yet */ }
  };

  const handleDownload = async (accountId?: number) => {
    if (!post) return;
    const key = accountId ? String(accountId) : "all";
    setDownloading(key);
    try {
      await downloadFile(post.id, accountId);
    } catch { toast.error("Download failed"); }
    finally { setDownloading(null); }
  };

  const fontWeights = ["Light", "Regular", "Medium", "SemiBold", "Bold", "ExtraBold", "Black"];

  const openSlideEditor = (accountId: number, slideNumber: number) => {
    const slide = post?.slides?.find((s: any) => s.slide_number === slideNumber);
    if (!slide) return;
    const t = slide.type;
    // Determine source image: variation replacement if present, else master
    const variation = slide.variations?.find((v: any) => v.account_id === accountId);
    const source = (variation?.action && variation.action !== "keep" && variation.replacement_image_path)
      ? variation.replacement_image_path
      : slide.master_image_path;
    setEditingSlide({
      accountId, slideNumber, slideType: t,
      titleText: slide.title_text || "",
      bodyText: slide.body_text || "",
      ctaText: slide.cta_text || "",
      fontSizeTitle: t === "hook" ? 56 : t === "content" ? 52 : 48,
      fontSizeBody: t === "content" ? 38 : 34,
      fontSizeCta: 42,
      yRatioTitle: t === "hook" ? 0.30 : t === "content" ? 0.28 : 0.25,
      yRatioBody: t === "content" ? 0.48 : 0.45,
      yRatioCta: 0.75,
      xRatioTitle: 0.5, xRatioBody: 0.5, xRatioCta: 0.5,
      scaleTitle: 1.0, scaleBody: 1.0, scaleCta: 1.0,
      fontWeight: "Bold",
      textStyle: "stroke",
      sourceImagePath: source || "",
    });
  };

  const handleRegenerateSlide = async () => {
    if (!post || !editingSlide) return;
    setRegenerating(true);
    try {
      await regenerateSlide(post.id, {
        account_id: editingSlide.accountId,
        slide_number: editingSlide.slideNumber,
        title_text: editingSlide.titleText,
        body_text: editingSlide.bodyText,
        cta_text: editingSlide.ctaText,
        font_size_title: editingSlide.fontSizeTitle,
        font_size_body: editingSlide.fontSizeBody,
        font_size_cta: editingSlide.fontSizeCta,
        y_ratio_title: editingSlide.yRatioTitle,
        y_ratio_body: editingSlide.yRatioBody,
        y_ratio_cta: editingSlide.yRatioCta,
        x_ratio_title: editingSlide.xRatioTitle,
        x_ratio_body: editingSlide.xRatioBody,
        x_ratio_cta: editingSlide.xRatioCta,
        scale_title: editingSlide.scaleTitle,
        scale_body: editingSlide.scaleBody,
        scale_cta: editingSlide.scaleCta,
        font_weight: editingSlide.fontWeight,
        text_style: editingSlide.textStyle,
      });
      await loadOutputSlides();
      setCacheKey(Date.now());
      toast.success("Slide regenerated");
    } catch { toast.error("Regeneration failed"); }
    finally { setRegenerating(false); }
  };

  const handleRegenerateVideo = async (accountId: number) => {
    if (!post) return;
    setRegeneratingVideo(accountId);
    try {
      await regenerateVideo(post.id, accountId);
      await loadOutputSlides();
      await reloadPost();
      setCacheKey(Date.now());
      toast.success("Video regenerated");
    } catch (e: any) { toast.error("Video regeneration failed: " + (e.response?.data?.detail || e.message)); }
    finally { setRegeneratingVideo(null); }
  };

  const inputClass = "w-full rounded-lg border border-border bg-background px-4 py-2.5 text-base sm:text-sm outline-none transition-colors focus:border-foreground placeholder:text-muted-foreground";

  return (
    <div className="mx-auto max-w-5xl">
      <div className="mb-6 md:mb-8">
        <h1 className="text-xl md:text-2xl font-bold tracking-tight">Create New Post</h1>
        <p className="mt-1 text-sm text-muted-foreground">Import slides, edit text, manage variations, and generate content.</p>
      </div>

      {/* Step Indicators */}
      <div className="mb-6 md:mb-8 -mx-4 px-4 md:mx-0 md:px-0 overflow-x-auto">
        <div className="flex min-w-max items-center gap-1.5 md:gap-2">
          {(["import", "edit", "variations", "generate"] as Step[]).map((s, i) => (
            <div key={s} className="flex items-center gap-1.5 md:gap-2">
              <button
                onClick={() => (post || s === "import") && setStep(s)}
                className={`flex items-center gap-1.5 md:gap-2 rounded-lg px-3 md:px-4 py-2 text-xs md:text-sm font-medium transition-colors whitespace-nowrap ${
                  step === s
                    ? "bg-foreground text-background"
                    : post
                    ? "bg-muted text-foreground hover:bg-muted/80"
                    : "bg-muted/50 text-muted-foreground"
                }`}
              >
                <span className={`flex h-5 w-5 items-center justify-center rounded-full text-xs ${
                  step === s ? "bg-background/20 text-background" : "bg-foreground/10"
                }`}>{i + 1}</span>
                {s === "import" ? "Import" : s === "edit" ? "Edit Slides" : s === "variations" ? "Variations" : "Generate"}
              </button>
              {i < 3 && <div className="h-px w-4 md:w-8 bg-border" />}
            </div>
          ))}
        </div>
      </div>

      {/* Step 1: Import */}
      {step === "import" && (
        <div className="rounded-2xl bg-card p-4 md:p-6">
          <div className="mb-5 flex gap-2">
            <button onClick={() => setImportMode("upload")}
              className={`flex items-center gap-1.5 sm:gap-2 whitespace-nowrap rounded-lg px-3 sm:px-4 py-2 text-xs sm:text-sm font-medium transition-colors ${
                importMode === "upload" ? "bg-foreground text-background" : "bg-muted text-muted-foreground hover:text-foreground"
              }`}>
              <Upload className="h-4 w-4" /> Upload <span className="hidden sm:inline">Slides</span>
            </button>
            <button onClick={() => setImportMode("tiktok")}
              className={`flex items-center gap-1.5 sm:gap-2 whitespace-nowrap rounded-lg px-3 sm:px-4 py-2 text-xs sm:text-sm font-medium transition-colors ${
                importMode === "tiktok" ? "bg-foreground text-background" : "bg-muted text-muted-foreground hover:text-foreground"
              }`}>
              <Link2 className="h-4 w-4" /> <span className="sm:hidden">Import</span><span className="hidden sm:inline">Import from TikTok</span>
            </button>
          </div>

          <div className="space-y-4">
            <div>
              <label className="mb-1.5 block text-sm font-medium">Brand</label>
              <select onChange={(e) => e.target.value && setSelectedBrand(Number(e.target.value))}
                className={inputClass} defaultValue="">
                <option value="" disabled>Select a brand...</option>
                {brands.map((b: any) => <option key={b.id} value={b.id}>{b.name}</option>)}
              </select>
            </div>

            {importMode === "tiktok" ? (
              <div key="tiktok-mode">
                <div>
                  <label className="mb-1.5 block text-sm font-medium">TikTok Post URL</label>
                  <input value={tiktokUrl} onChange={(e) => setTiktokUrl(e.target.value)}
                    placeholder="https://www.tiktok.com/@user/photo/1234..." className={inputClass} />
                </div>
                <button onClick={handleImport} disabled={importing}
                  className="mt-4 inline-flex items-center gap-2 rounded-lg bg-foreground px-5 py-2.5 text-sm font-medium text-background transition-opacity hover:opacity-90 disabled:opacity-50">
                  {importing ? <><Loader2 className="h-4 w-4 animate-spin" /> Importing...</> : <><Download className="h-4 w-4" /> Import Slides</>}
                </button>
              </div>
            ) : (
              <div key="upload-mode">
                <div>
                  <label className="mb-1.5 block text-sm font-medium">Slide Images (select multiple, in order)</label>
                  <input type="file" accept="image/*" multiple onChange={(e) => setManualFiles(Array.from(e.target.files || []))}
                    className="w-full rounded-lg border border-border bg-background px-4 py-2.5 text-base sm:text-sm outline-none focus:border-foreground file:mr-3 file:border-0 file:bg-transparent file:text-sm file:font-medium" />
                  {manualFiles.length > 0 && <p className="mt-1 text-xs text-muted-foreground">{manualFiles.length} file(s) selected</p>}
                </div>
                <div>
                  <label className="mb-1.5 block text-sm font-medium">Caption (optional)</label>
                  <input value={manualCaption} onChange={(e) => setManualCaption(e.target.value)} placeholder="Post caption..." className={inputClass} />
                </div>
                <button onClick={handleManualUpload} disabled={importing}
                  className="mt-4 inline-flex items-center gap-2 rounded-lg bg-foreground px-5 py-2.5 text-sm font-medium text-background transition-opacity hover:opacity-90 disabled:opacity-50">
                  {importing ? <><Loader2 className="h-4 w-4 animate-spin" /> Uploading...</> : <><Upload className="h-4 w-4" /> Upload & Create Post</>}
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Step 2: Edit Slides */}
      {step === "edit" && post && (
        <div className="space-y-4">
          <div className="rounded-2xl bg-card p-5">
            <label className="mb-1.5 block text-sm font-medium">Caption (shared across all platforms)</label>
            <textarea value={post.caption || ""}
              onChange={(e) => handleCaptionChange(e.target.value)}
              onBlur={(e) => handleCaptionChange(e.target.value, true)}
              placeholder="Enter caption..." rows={2}
              className="w-full rounded-lg border border-border bg-background px-4 py-2.5 text-base sm:text-sm outline-none focus:border-foreground placeholder:text-muted-foreground resize-none" />
          </div>

          <div className="flex items-center justify-between">
            <h2 className="flex items-center gap-2 text-base font-semibold">
              <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-foreground">
                <Type className="h-3.5 w-3.5 text-background" />
              </div>
              Slides (OCR-extracted text — review & edit)
            </h2>
            <button onClick={handleRerunOcr} disabled={rerunningOcr}
              className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-lg border border-border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted disabled:opacity-50">
              {rerunningOcr ? <Loader2 className="h-3 w-3 animate-spin" /> : <Sparkles className="h-3 w-3" />}
              Re-run OCR
            </button>
          </div>

          {post.slides?.map((slide: any) => (
            <div key={slide.id} className="rounded-2xl bg-card p-4 md:p-5">
              <div className="flex flex-col gap-4 sm:flex-row">
                <div className="flex-shrink-0">
                  {slide.master_image_path ? (
                    <img src={fileUrl(slide.master_image_path)} alt={`Slide ${slide.slide_number}`}
                      className="h-40 w-30 rounded-lg object-cover cursor-pointer hover:opacity-80 transition-opacity"
                      onClick={() => setExpandedImage(fileUrl(slide.master_image_path))} />
                  ) : (
                    <div className="flex h-40 w-30 items-center justify-center rounded-lg bg-muted">
                      <ImageIcon className="h-8 w-8 text-muted-foreground/50" />
                    </div>
                  )}
                </div>

                <div className="flex-1 space-y-3 min-w-0">
                  <div className="flex flex-wrap items-center gap-2 md:gap-3">
                    <span className={`rounded-md px-2 py-0.5 text-[11px] font-medium ${
                      slide.type === "hook" ? "bg-foreground text-background" :
                      slide.type === "cta" ? "bg-foreground/10 text-foreground" :
                      "bg-muted text-muted-foreground"
                    }`}>
                      Slide {slide.slide_number} — {slide.type}
                    </span>
                    <select value={slide.type} onChange={(e) => e.target.value && handleSlideUpdate(slide.slide_number, "type", e.target.value)}
                      className="rounded-lg border border-border bg-background px-3 py-1 text-xs outline-none focus:border-foreground">
                      <option value="hook">Hook</option>
                      <option value="content">Content</option>
                      <option value="cta">CTA</option>
                    </select>
                    <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                      <input type="checkbox" checked={slide.has_face}
                        onChange={(e) => handleSlideUpdate(slide.slide_number, "has_face", e.target.checked)}
                        className="rounded" />
                      Has face
                    </label>
                  </div>

                  <div>
                    <label className="mb-1 block text-xs font-medium text-muted-foreground">Title Text</label>
                    <input value={slide.title_text || ""}
                      onChange={(e) => handleSlideUpdate(slide.slide_number, "title_text", e.target.value)}
                      className={inputClass} placeholder="e.g. 1#. The check up before the cleanup!" />
                  </div>

                  <div>
                    <label className="mb-1 block text-xs font-medium text-muted-foreground">Body Text</label>
                    <textarea value={slide.body_text || ""}
                      onChange={(e) => handleSlideUpdate(slide.slide_number, "body_text", e.target.value)}
                      className="w-full rounded-lg border border-border bg-background px-4 py-2.5 text-base sm:text-sm outline-none focus:border-foreground placeholder:text-muted-foreground resize-none"
                      rows={2} placeholder="Description text..." />
                  </div>

                  {slide.type === "cta" && (
                    <div>
                      <label className="mb-1 block text-xs font-medium text-muted-foreground">CTA Text</label>
                      <input value={slide.cta_text || ""}
                        onChange={(e) => handleSlideUpdate(slide.slide_number, "cta_text", e.target.value)}
                        className={inputClass} placeholder="e.g. Search tryautobrush on google to grab yours now" />
                    </div>
                  )}
                </div>
              </div>
            </div>
          ))}

          <button onClick={async () => {
              // Flush any in-flight debounced saves so a quick edit-then-click
              // doesn't lose the last keystrokes when the page reloads on
              // step 3 / 4.
              if (captionTimer.current) {
                clearTimeout(captionTimer.current);
                try { await schedulePost(post.id, { caption: post.caption || "" }); }
                catch { toast.error("Failed to save caption"); return; }
              }
              setStep("variations");
            }}
            className="inline-flex items-center gap-2 rounded-lg bg-foreground px-5 py-2.5 text-sm font-medium text-background transition-opacity hover:opacity-90">
            Next: Edit Variations
          </button>
        </div>
      )}

      {/* Step 3: Variations */}
      {step === "variations" && post && (
        <div className="space-y-4">
          <h2 className="flex items-center gap-2 text-base font-semibold">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-foreground">
              <Sparkles className="h-3.5 w-3.5 text-background" />
            </div>
            Slide Variations per Account
          </h2>
          <p className="text-sm text-muted-foreground">
            For each account, choose which slides to keep, replace with your own image, or generate with AI.
          </p>

          {/* Tab buttons */}
          <div className="overflow-x-auto -mx-4 px-4 md:mx-0 md:px-0">
            <div className="flex min-w-max gap-1 rounded-lg border border-border p-1">
              {post.brand?.accounts?.map((acc: any, idx: number) => (
                <button key={acc.id} onClick={() => setActiveTab(idx)}
                  className={`rounded-md px-3 md:px-4 py-2 text-xs md:text-sm font-medium transition-colors whitespace-nowrap ${
                    activeTab === idx ? "bg-foreground text-background" : "text-muted-foreground hover:text-foreground"
                  }`}>
                  {acc.name}
                  {acc.role === "master" && <span className="ml-1.5 text-[10px] opacity-60">master</span>}
                </button>
              ))}
            </div>
          </div>

          {/* Tab content */}
          {post.brand?.accounts?.map((acc: any, idx: number) => {
            if (activeTab !== idx) return null;
            return (
              <div key={acc.id} className="space-y-3">
                {post.slides?.map((slide: any) => {
                  const variation = slide.variations?.find((v: any) => v.account_id === acc.id);
                  if (!variation) return null;

                  return (
                    <div key={slide.id} className="rounded-2xl bg-card p-4 md:p-5">
                      <div className="flex flex-col gap-4 md:flex-row md:items-center">
                        <div className="flex items-center gap-3 md:contents">
                        <div className="flex-shrink-0 text-center">
                          <p className="mb-1 text-[10px] text-muted-foreground">Original</p>
                          {slide.master_image_path ? (
                            <img src={fileUrl(slide.master_image_path)} alt="" className="h-24 w-18 rounded-lg object-cover cursor-pointer hover:opacity-80 transition-opacity" onClick={() => setExpandedImage(fileUrl(slide.master_image_path))} />
                          ) : (
                            <div className="flex h-24 w-18 items-center justify-center rounded-lg bg-muted"><ImageIcon className="h-6 w-6 text-muted-foreground/50" /></div>
                          )}
                        </div>

                        <span className="text-muted-foreground/40">→</span>

                        <div className="flex-shrink-0 text-center">
                          <p className="mb-1 text-[10px] text-muted-foreground">Replacement</p>
                          {variation.replacement_image_path ? (
                            <img src={fileUrl(variation.replacement_image_path)} alt="" className="h-24 w-18 rounded-lg object-cover cursor-pointer hover:opacity-80 transition-opacity" onClick={() => setExpandedImage(fileUrl(variation.replacement_image_path))} />
                          ) : (
                            <div className="flex h-24 w-18 items-center justify-center rounded-lg border border-dashed border-border bg-muted/50">
                              <span className="text-[10px] text-muted-foreground/50">Same</span>
                            </div>
                          )}
                        </div>
                        </div>

                        <div className="flex-1 min-w-0">
                          <div className="mb-2 flex items-center gap-2">
                            <span className="rounded-md border border-border px-2 py-0.5 text-[11px]">Slide {slide.slide_number}</span>
                            <span className={`rounded-md px-2 py-0.5 text-[11px] font-medium ${
                              variation.action === "keep" ? "bg-muted text-muted-foreground" : "bg-foreground/10 text-foreground"
                            }`}>{variation.action}</span>
                            {variation.status === "generated" && (
                              <span className="rounded-md bg-foreground/10 px-2 py-0.5 text-[11px] font-medium">needs approval</span>
                            )}
                            {variation.status === "approved" && (
                              <span className="rounded-md bg-foreground px-2 py-0.5 text-[11px] font-medium text-background">approved</span>
                            )}
                          </div>
                          <p className="text-sm font-medium text-foreground">{slide.title_text}</p>
                          {slide.body_text && (
                            <p className="mt-0.5 text-xs text-muted-foreground">{slide.body_text}</p>
                          )}
                          {slide.cta_text && (
                            <p className="mt-0.5 text-xs font-medium text-lime">{slide.cta_text}</p>
                          )}
                        </div>

                        {acc.role !== "master" && (
                          <div className="grid grid-cols-2 gap-1.5 md:flex md:flex-col">
                            <button onClick={() => handleKeep(variation.id)}
                              className="rounded-lg border border-border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted">
                              Keep Original
                            </button>
                            <button
                              className="rounded-lg border border-border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted"
                              onClick={() => {
                                const input = document.createElement("input");
                                input.type = "file"; input.accept = "image/*";
                                input.onchange = (e) => {
                                  const file = (e.target as HTMLInputElement).files?.[0];
                                  if (file) handleUploadVariation(variation.id, file);
                                };
                                input.click();
                              }}>
                              <Upload className="mr-1 inline h-3 w-3" /> Upload
                            </button>
                            <button onClick={() => handleGenerateAI(variation.id)}
                              className="rounded-lg border border-border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted">
                              <Wand2 className="mr-1 inline h-3 w-3" /> AI Generate
                            </button>
                            {variation.status === "generated" && (
                              <button onClick={() => handleApprove(variation.id)}
                                className="rounded-lg bg-foreground px-3 py-1.5 text-xs font-medium text-background transition-opacity hover:opacity-90">
                                <Check className="mr-1 inline h-3 w-3" /> Approve
                              </button>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            );
          })}

          <button onClick={() => setStep("generate")}
            className="inline-flex items-center gap-2 rounded-lg bg-foreground px-5 py-2.5 text-sm font-medium text-background transition-opacity hover:opacity-90">
            Next: Generate & Schedule
          </button>
        </div>
      )}

      {/* Step 4: Generate */}
      {step === "generate" && post && (
        <div className="space-y-6">
          {/* Generate Content */}
          <div className="rounded-2xl bg-card p-4 md:p-6">
            <h2 className="mb-2 text-base font-semibold">Generate Content</h2>
            <p className="mb-5 text-sm text-muted-foreground">
              This will apply text overlays to all slides and create 9:16 videos with transitions for all {post.brand?.accounts?.length || 0} accounts.
            </p>

            {generating && (
              <div className="mb-4">
                <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
                  <div className="h-full rounded-full bg-foreground transition-all duration-500" style={{ width: `${genProgress}%` }} />
                </div>
                <p className="mt-1.5 text-xs text-muted-foreground">Generating slides and videos...</p>
              </div>
            )}

            <div className="flex gap-3">
              <button onClick={handleGenerate} disabled={generating}
                className="inline-flex items-center gap-2 rounded-lg bg-foreground px-5 py-2.5 text-sm font-medium text-background transition-opacity hover:opacity-90 disabled:opacity-50">
                {generating ? <><Loader2 className="h-4 w-4 animate-spin" /> Generating...</> : <><Play className="h-4 w-4" /> Generate All</>}
              </button>
              {post.outputs && post.outputs.length > 0 && (
                <button onClick={handleGenerate} disabled={generating}
                  className="inline-flex items-center gap-2 rounded-lg border border-border px-5 py-2.5 text-sm font-medium transition-colors hover:bg-muted disabled:opacity-50">
                  <RefreshCw className="h-4 w-4" /> Regenerate
                </button>
              )}
            </div>
          </div>

          {/* Schedule & Post */}
          <div className="rounded-2xl bg-card p-4 md:p-6">
            <h2 className="mb-5 text-base font-semibold">Schedule & Music</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="mb-1.5 block text-sm font-medium">Post Time</label>
                <input type="time" value={scheduleTime} onChange={(e) => setScheduleTime(e.target.value)} className={inputClass} />
                {selectedBrandData && (
                  <p className="mt-1.5 text-xs text-muted-foreground">
                    Timezone: {selectedBrandData.timezone} | Defaults: {selectedBrandData.default_post_times}
                  </p>
                )}
              </div>
              <div className="sm:col-span-2">
                <label className="mb-1.5 block text-sm font-medium">Background Music — per platform</label>
                <p className="mb-2 text-xs text-muted-foreground">
                  TikTok posts as a swipeable photo slideshow (uses TikTok's own sound library). YouTube / Instagram / Facebook get rendered videos with the music you select here.
                </p>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  {PLATFORMS.map((p) => (
                    <div key={p}>
                      <label className="mb-1 block text-xs font-medium text-muted-foreground">{PLAT_LABEL[p]}</label>
                      <select
                        value={platMusic[p] ? String(platMusic[p]) : "0"}
                        onChange={(e) =>
                          setPlatMusic((prev) => ({
                            ...prev,
                            [p]: e.target.value && e.target.value !== "0" ? Number(e.target.value) : null,
                          }))
                        }
                        className={inputClass}
                      >
                        <option value="0">No music</option>
                        {platMusicLib[p].map((t: any) => (
                          <option key={t.id} value={String(t.id)}>
                            {t.name} {t.genre && `(${t.genre})`}
                          </option>
                        ))}
                      </select>
                    </div>
                  ))}
                </div>
              </div>
            </div>
            {/* Failed platform errors — shown for both manual Post Now failures
                and scheduled dispatch failures. Persisted in the outputs table. */}
            {failedOutputs.length > 0 && post?.id && (
              <div className="mt-4">
                <FailedOutputsSection
                  postId={post.id}
                  failedOutputs={failedOutputs}
                  setFailedOutputs={setFailedOutputs}
                />
              </div>
            )}

            <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:gap-3">
              <button onClick={handleSchedule}
                disabled={!allTiktokValid}
                title={!allTiktokValid ? "Finish TikTok setup on all variations below first" : ""}
                className="inline-flex min-h-[44px] items-center justify-center gap-2 rounded-lg border border-border px-5 py-2.5 text-sm font-medium transition-colors hover:bg-muted disabled:opacity-50">
                <Clock className="h-4 w-4" /> Save Schedule
              </button>
              <button
                disabled={!allTiktokValid}
                title={!allTiktokValid ? "Finish TikTok setup on all variations below first" : ""}
                onClick={async () => {
                  if (!post?.id) { toast.error("Generate the post first"); return; }
                  setPostingResults(null);
                  setPostingModalOpen(true);
                  try {
                    const res = await postNow(post.id);
                    setPostingResults(res.results || []);
                    // Refresh failed outputs so the persistent section updates
                    getFailedOutputs(post.id).then((fo) => setFailedOutputs(fo || [])).catch(() => {});
                  } catch (e: any) {
                    setPostingModalOpen(false);
                    toast.error(e?.response?.data?.detail || "Post Now failed");
                  }
                }}
                className="inline-flex min-h-[44px] items-center justify-center gap-2 rounded-lg bg-lime px-5 py-2.5 text-sm font-bold text-black transition-all hover:brightness-95 disabled:opacity-50 disabled:hover:brightness-100">
                <Send className="h-4 w-4" /> Post Now
              </button>
            </div>
          </div>

          {/* TikTok posting settings — per non-master variation with TT connected.
              TikTok requires the user to pick privacy and disclosure on every
              flow with no default value, so settings live here on the Generate
              tab (not in admin / global). Cards are collapsed by default. */}
          {post.outputs && post.outputs.length > 0 && (() => {
            const ttCards = post.outputs
              .map((out: any) => {
                const acc = post.brand?.accounts?.find((a: any) => a.id === out.account_id);
                if (!acc) return null;
                if (acc.role === "master") return null; // master skips TikTok
                if (!acc.tiktok_token && !acc.tiktok_connected) return null; // no TT connected
                return (
                  <TikTokSettingsCard
                    key={out.id}
                    entityId={out.id}
                    entityLabel={acc.name || `Account ${acc.id}`}
                    creatorInfoAccountId={acc.id}
                    creatorInfoKind="brand_account"
                    mediaType="photo"
                    initialValues={out}
                    onSave={(payload) => updateOutputTiktokSettings(out.id, payload).then(() => {})}
                    onValidityChange={onTiktokValidity}
                  />
                );
              })
              .filter(Boolean);
            if (ttCards.length === 0) return null;
            return (
              <div className="rounded-2xl bg-card p-4 md:p-6">
                <h2 className="mb-1 text-base font-semibold">TikTok posting settings</h2>
                <p className="mb-4 text-xs text-muted-foreground">
                  TikTok requires you to pick privacy and disclosure for every post — there's no global default. Configure each variation below before posting.
                </p>
                <div className="space-y-2">{ttCards}</div>
              </div>
            );
          })()}

          {/* Preview & Downloads */}
          {post.outputs && post.outputs.length > 0 && (
            <div className="rounded-2xl bg-card p-4 md:p-6">
              <div className="mb-5 flex items-center justify-between">
                <h2 className="text-base font-semibold">Preview & Downloads</h2>
                <button onClick={loadOutputSlides}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted">
                  <Eye className="h-3 w-3" /> Load Previews
                </button>
              </div>

              {/* Account previews */}
              {outputSlides.length > 0 && (
                <div className="mb-5">
                  <div className="mb-3 overflow-x-auto -mx-4 px-4 md:mx-0 md:px-0">
                    <div className="flex min-w-max gap-1 rounded-lg border border-border p-1">
                      {outputSlides.map((out: any, idx: number) => (
                        <button key={out.account_id} onClick={() => setPreviewTab(idx)}
                          className={`rounded-md px-3 md:px-4 py-2 text-xs md:text-sm font-medium transition-colors whitespace-nowrap ${
                            previewTab === idx ? "bg-foreground text-background" : "text-muted-foreground hover:text-foreground"
                          }`}>
                          {out.account_name}
                          {out.account_role === "master" && <span className="ml-1.5 text-[10px] opacity-60">master</span>}
                        </button>
                      ))}
                    </div>
                  </div>

                  {outputSlides.map((out: any, idx: number) => {
                    if (previewTab !== idx) return null;
                    const isMaster = out.account_role === "master";
                    return (
                      <div key={out.account_id} className="space-y-4">
                        {/* TikTok Slides (3:4) — variation accounts only (master skips TikTok) */}
                        {!isMaster && out.slides_3x4?.length > 0 && (
                          <div>
                            <p className="mb-2 text-xs font-medium text-muted-foreground">
                              TikTok Slides (3:4)
                            </p>
                            <div className="grid grid-cols-2 gap-2 md:gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
                              {out.slides_3x4.map((filePath: string, si: number) => (
                                <div key={si} className="group relative">
                                  <img src={`${fileUrl(filePath)}?v=${cacheKey || 0}`} alt={`Slide ${si + 1}`}
                                    className="w-full rounded-lg border border-border object-cover cursor-pointer hover:opacity-80 transition-opacity"
                                    style={{ aspectRatio: "3/4" }}
                                    onClick={() => setExpandedImage(`${fileUrl(filePath)}?v=${cacheKey || 0}`)} />
                                  <span className="absolute bottom-1 left-1 rounded bg-black/70 px-1.5 py-0.5 text-[10px] text-white">
                                    {si + 1}
                                  </span>
                                  <button
                                    onClick={(e) => { e.stopPropagation(); openSlideEditor(out.account_id, si + 1); }}
                                    className="absolute bottom-1 right-1 rounded bg-black/70 px-1.5 py-0.5 text-[10px] text-white opacity-0 group-hover:opacity-100 transition-opacity hover:bg-black/90"
                                    title="Edit & regenerate this slide"
                                  >
                                    <RotateCcw className="inline h-3 w-3" />
                                  </button>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {/* Per-platform videos — YouTube / Instagram / Facebook */}
                        <div>
                          <div className="mb-2 flex items-center justify-between">
                            <p className="text-xs font-medium text-muted-foreground">
                              Videos (9:16) — per platform
                            </p>
                          </div>
                          <div className="mb-3 flex gap-1 rounded-lg border border-border p-1 w-fit">
                            {PLATFORMS.map((p) => (
                              <button key={p} onClick={() => setPreviewPlatform(p)}
                                className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                                  previewPlatform === p ? "bg-foreground text-background" : "text-muted-foreground hover:text-foreground"
                                }`}>
                                {PLAT_LABEL[p]}
                              </button>
                            ))}
                          </div>
                          {(() => {
                            const pPath = out[`${previewPlatform}_video_path`] || out.video_path;
                            const busyKey = `${out.account_id}:${previewPlatform}`;
                            return (
                              <div className="space-y-2">
                                <div className="flex justify-end">
                                  <button onClick={() => handleRegeneratePlatformVideo(out.account_id, previewPlatform)}
                                    disabled={regeneratingPlatform === busyKey}
                                    className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted disabled:opacity-50">
                                    {regeneratingPlatform === busyKey
                                      ? <><Loader2 className="h-3 w-3 animate-spin" /> Regenerating...</>
                                      : <><RotateCcw className="h-3 w-3" /> Regenerate {PLAT_LABEL[previewPlatform]}</>}
                                  </button>
                                </div>
                                {pPath ? (
                                  <video
                                    controls
                                    className="w-full max-w-xs rounded-lg border border-border"
                                    style={{ aspectRatio: "9/16" }}
                                    src={`${fileUrl(pPath)}?v=${cacheKey || 0}`}
                                  >
                                    Your browser does not support the video tag.
                                  </video>
                                ) : out.slides_9x16 && out.slides_9x16.length > 0 ? (
                            <div className="grid grid-cols-2 gap-2 md:gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
                              {out.slides_9x16.map((filePath: string, si: number) => (
                                <div key={si} className="group relative">
                                  <img src={`${fileUrl(filePath)}?v=${cacheKey || 0}`} alt={`9:16 Slide ${si + 1}`}
                                    className="w-full rounded-lg border border-border object-cover cursor-pointer hover:opacity-80 transition-opacity"
                                    style={{ aspectRatio: "9/16" }}
                                    onClick={() => setExpandedImage(`${fileUrl(filePath)}?v=${cacheKey || 0}`)} />
                                  <span className="absolute bottom-1 left-1 rounded bg-black/70 px-1.5 py-0.5 text-[10px] text-white">
                                    {si + 1}
                                  </span>
                                </div>
                              ))}
                            </div>
                          ) : (
                            <p className="text-xs text-muted-foreground">No video generated yet. Click Generate All first.</p>
                          )}
                              </div>
                            );
                          })()}
                        </div>

                        {/* Caption */}
                        {post.caption && (
                          <div className="rounded-xl bg-muted/50 px-4 py-3">
                            <p className="mb-1 text-[10px] font-medium text-muted-foreground">Caption</p>
                            <p className="text-xs text-foreground">{post.caption}</p>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}

              {/* Download buttons */}
              <div className="space-y-2">
                {post.outputs.map((out: any) => {
                  const acc = post.brand?.accounts?.find((a: any) => a.id === out.account_id);
                  return (
                    <div key={out.id} className="flex flex-col gap-2 rounded-xl bg-muted/50 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
                      <div className="flex flex-wrap items-center gap-2 sm:gap-3">
                        <span className="text-sm font-medium">{acc?.name || `Account ${out.account_id}`}</span>
                        <span className="rounded-full bg-muted px-2.5 py-0.5 text-xs font-medium capitalize">{out.posting_status}</span>
                      </div>
                      <button onClick={() => handleDownload(out.account_id)} disabled={downloading === String(out.account_id)}
                        className="inline-flex min-h-[36px] items-center justify-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted disabled:opacity-50 self-start sm:self-auto">
                        {downloading === String(out.account_id) ? <Loader2 className="h-3 w-3 animate-spin" /> : <Download className="h-3 w-3" />}
                        Download ZIP
                      </button>
                    </div>
                  );
                })}
                <button onClick={() => handleDownload()} disabled={downloading === "all"}
                  className="mt-2 inline-flex items-center gap-2 rounded-lg bg-foreground px-5 py-2.5 text-sm font-medium text-background transition-opacity hover:opacity-90 disabled:opacity-50">
                  {downloading === "all" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
                  Download All
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Slide Editor Modal — side-by-side live preview + controls */}
      {editingSlide && typeof document !== "undefined" && createPortal(
        <div className="fixed inset-0 z-[9998] flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
          onClick={() => setEditingSlide(null)}>
          <div className="flex max-h-[92vh] w-full max-w-5xl flex-col rounded-2xl bg-card shadow-2xl overflow-hidden" onClick={(e) => e.stopPropagation()}>
            <div className="flex shrink-0 items-center justify-between border-b border-border px-6 py-4">
              <h3 className="text-base font-semibold">Edit Slide {editingSlide.slideNumber} Overlay</h3>
              <button onClick={() => setEditingSlide(null)} className="rounded-full p-1 hover:bg-muted">
                <span className="text-lg leading-none">&times;</span>
              </button>
            </div>

            <div className="grid min-h-0 flex-1 grid-cols-1 md:grid-cols-5 gap-0 overflow-y-auto md:overflow-hidden">
              {/* Left: Live preview */}
              <div className="md:col-span-2 bg-black/40 p-4 md:p-5 flex items-start justify-center md:overflow-y-auto">
                <div className="relative w-full max-w-[360px]" style={{ aspectRatio: "3/4" }}>
                  {editingSlide.sourceImagePath ? (
                    <img src={fileUrl(editingSlide.sourceImagePath)}
                      alt="Source" className="absolute inset-0 h-full w-full rounded-lg object-cover" />
                  ) : (
                    <div className="absolute inset-0 flex items-center justify-center rounded-lg bg-muted">
                      <ImageIcon className="h-10 w-10 text-muted-foreground/50" />
                    </div>
                  )}

                  {/* Live text overlays (CSS-rendered to mimic Pillow output) */}
                  {(() => {
                    // Preview uses a 3:4 frame; backend renders at 768x1024.
                    // We scale font sizes by (previewWidth / 768). Since container is responsive,
                    // use viewport-based CSS: font size is px where 1px ≈ 1/768 of preview width.
                    // Using aspect-ratio 3/4, previewWidth = containerWidth, previewHeight = containerWidth * 4/3.
                    // Approx: 1 backend px ≈ previewWidth * (1/768) CSS px.
                    const scale = 360 / 768; // approximate; parent has max-w-[360px]
                    // Must match backend (services/overlay.py uses TikTok Sans Variable)
                    const fontFamily = `"TikTok Sans", sans-serif`;
                    const baseFontWeight = editingSlide.fontWeight === "Light" ? 300
                      : editingSlide.fontWeight === "Regular" ? 400
                      : editingSlide.fontWeight === "Medium" ? 500
                      : editingSlide.fontWeight === "SemiBold" ? 600
                      : editingSlide.fontWeight === "Bold" ? 700
                      : editingSlide.fontWeight === "ExtraBold" ? 800
                      : 900;

                    const renderBlock = (text: string, fontSize: number, yRatio: number, xRatio: number, zoom: number, key: string) => {
                      if (!text) return null;
                      // Font-size is ALWAYS the raw value from the Size slider (scaled for preview only).
                      // Zoom is a pure CSS transform — it visually grows/shrinks the block without
                      // touching the font-size reading. This matches the PIL backend where we
                      // render the text at the exact font_size then scale the rendered layer.
                      const renderedFontPx = fontSize * scale; // preview scale only (backend→preview)
                      const leftPct = xRatio * 100;
                      // Backend wraps at 88% of image width, uses line-height 1.3, stroke_width = max(3, size/14)
                      if (editingSlide.textStyle === "background") {
                        return (
                          <div key={key} style={{
                            position: "absolute",
                            left: `${leftPct}%`,
                            top: `${yRatio * 100}%`,
                            transform: `translate(-50%, -50%) scale(${zoom})`,
                            transformOrigin: "center center",
                            textAlign: "center",
                            pointerEvents: "none",
                            width: "88%",
                          }}>
                            <span style={{
                              display: "inline-block",
                              background: "rgba(0,0,0,0.67)",
                              color: "white",
                              fontFamily,
                              fontWeight: baseFontWeight,
                              fontSize: `${renderedFontPx}px`,
                              lineHeight: 1.3,
                              padding: `${8 * scale}px ${16 * scale}px`,
                              borderRadius: `${(fontSize * 1.3 + 16) * 0.35 * scale}px`,
                              wordBreak: "break-word",
                            }}>{text}</span>
                          </div>
                        );
                      }
                      const sw = Math.max(3, Math.floor(fontSize / 14)) * scale;
                      const style: React.CSSProperties = {
                        position: "absolute",
                        left: `${leftPct}%`,
                        top: `${yRatio * 100}%`,
                        transform: `translate(-50%, -50%) scale(${zoom})`,
                        transformOrigin: "center center",
                        width: "88%",
                        textAlign: "center",
                        fontFamily,
                        fontWeight: baseFontWeight,
                        fontSize: `${renderedFontPx}px`,
                        lineHeight: 1.3,
                        color: "white",
                        wordBreak: "break-word",
                        pointerEvents: "none",
                        WebkitTextStroke: `${sw}px black`,
                        paintOrder: "stroke fill" as any,
                      };
                      return <div key={key} style={style}>{text}</div>;
                    };

                    const t = editingSlide.slideType;
                    const blocks: React.ReactNode[] = [];
                    if (t === "hook") {
                      blocks.push(renderBlock(editingSlide.titleText || editingSlide.bodyText, editingSlide.fontSizeTitle, editingSlide.yRatioTitle, editingSlide.xRatioTitle, editingSlide.scaleTitle, "title"));
                    } else if (t === "content") {
                      blocks.push(renderBlock(editingSlide.titleText, editingSlide.fontSizeTitle, editingSlide.yRatioTitle, editingSlide.xRatioTitle, editingSlide.scaleTitle, "title"));
                      blocks.push(renderBlock(editingSlide.bodyText, editingSlide.fontSizeBody, editingSlide.yRatioBody, editingSlide.xRatioBody, editingSlide.scaleBody, "body"));
                    } else if (t === "cta") {
                      blocks.push(renderBlock(editingSlide.titleText, editingSlide.fontSizeTitle, editingSlide.yRatioTitle, editingSlide.xRatioTitle, editingSlide.scaleTitle, "title"));
                      blocks.push(renderBlock(editingSlide.bodyText, editingSlide.fontSizeBody, editingSlide.yRatioBody, editingSlide.xRatioBody, editingSlide.scaleBody, "body"));
                      blocks.push(renderBlock(editingSlide.ctaText, editingSlide.fontSizeCta, editingSlide.yRatioCta, editingSlide.xRatioCta, editingSlide.scaleCta, "cta"));
                    }
                    return blocks;
                  })()}
                </div>
              </div>

              {/* Right: Controls */}
              <div className="md:col-span-3 p-4 md:p-6 pb-8 space-y-4 md:overflow-y-auto min-h-0">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <label className="mb-1 block text-xs font-medium text-muted-foreground">Font Weight</label>
                    <select value={editingSlide.fontWeight}
                      onChange={(e) => setEditingSlide({ ...editingSlide, fontWeight: e.target.value })}
                      className={inputClass}>
                      {fontWeights.map((w) => (
                        <option key={w} value={w}>{w}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-medium text-muted-foreground">Text Style</label>
                    <div className="flex gap-1 rounded-lg border border-border p-1">
                      <button
                        onClick={() => setEditingSlide({ ...editingSlide, textStyle: "stroke" })}
                        className={`flex-1 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                          editingSlide.textStyle === "stroke" ? "bg-foreground text-background" : "text-muted-foreground hover:text-foreground"
                        }`}>
                        Outline
                      </button>
                      <button
                        onClick={() => setEditingSlide({ ...editingSlide, textStyle: "background" })}
                        className={`flex-1 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                          editingSlide.textStyle === "background" ? "bg-foreground text-background" : "text-muted-foreground hover:text-foreground"
                        }`}>
                        Background
                      </button>
                    </div>
                  </div>
                </div>

                {/* Title */}
                <div>
                  <label className="mb-1 block text-xs font-medium text-muted-foreground">Title Text</label>
                  <input value={editingSlide.titleText}
                    onChange={(e) => setEditingSlide({ ...editingSlide, titleText: e.target.value })}
                    className={inputClass} />
                </div>
                <div>
                  <div className="mb-1 flex justify-between text-xs font-medium text-muted-foreground">
                    <span>Title Size</span><span>{editingSlide.fontSizeTitle}px</span>
                  </div>
                  <input type="range" min={16} max={120} step={1} value={editingSlide.fontSizeTitle}
                    onChange={(e) => setEditingSlide({ ...editingSlide, fontSizeTitle: Number(e.target.value) })}
                    className="w-full accent-foreground" />
                </div>
                <div>
                  <div className="mb-1 flex justify-between text-xs font-medium text-muted-foreground">
                    <span>Title Y Position</span><span>{editingSlide.yRatioTitle.toFixed(2)}</span>
                  </div>
                  <input type="range" min={0} max={1} step={0.01} value={editingSlide.yRatioTitle}
                    onChange={(e) => setEditingSlide({ ...editingSlide, yRatioTitle: Number(e.target.value) })}
                    className="w-full accent-foreground" />
                </div>
                <div>
                  <div className="mb-1 flex justify-between text-xs font-medium text-muted-foreground">
                    <span>Title X Position</span><span>{editingSlide.xRatioTitle.toFixed(2)}</span>
                  </div>
                  <input type="range" min={0} max={1} step={0.01} value={editingSlide.xRatioTitle}
                    onChange={(e) => setEditingSlide({ ...editingSlide, xRatioTitle: Number(e.target.value) })}
                    className="w-full accent-foreground" />
                </div>
                <div>
                  <div className="mb-1 flex justify-between text-xs font-medium text-muted-foreground">
                    <span>Title Zoom (Scale)</span><span>{Math.round(editingSlide.scaleTitle * 100)}%</span>
                  </div>
                  <input type="range" min={0.3} max={3} step={0.01} value={editingSlide.scaleTitle}
                    onChange={(e) => setEditingSlide({ ...editingSlide, scaleTitle: Number(e.target.value) })}
                    className="w-full accent-foreground" />
                </div>

                {editingSlide.slideType !== "hook" && (
                  <>
                    <div>
                      <label className="mb-1 block text-xs font-medium text-muted-foreground">Body Text</label>
                      <textarea value={editingSlide.bodyText}
                        onChange={(e) => setEditingSlide({ ...editingSlide, bodyText: e.target.value })}
                        rows={2} className="w-full rounded-lg border border-border bg-background px-4 py-2.5 text-base sm:text-sm outline-none focus:border-foreground resize-none" />
                    </div>
                    <div>
                      <div className="mb-1 flex justify-between text-xs font-medium text-muted-foreground">
                        <span>Body Size</span><span>{editingSlide.fontSizeBody}px</span>
                      </div>
                      <input type="range" min={12} max={100} step={1} value={editingSlide.fontSizeBody}
                        onChange={(e) => setEditingSlide({ ...editingSlide, fontSizeBody: Number(e.target.value) })}
                        className="w-full accent-foreground" />
                    </div>
                    <div>
                      <div className="mb-1 flex justify-between text-xs font-medium text-muted-foreground">
                        <span>Body Y Position</span><span>{editingSlide.yRatioBody.toFixed(2)}</span>
                      </div>
                      <input type="range" min={0} max={1} step={0.01} value={editingSlide.yRatioBody}
                        onChange={(e) => setEditingSlide({ ...editingSlide, yRatioBody: Number(e.target.value) })}
                        className="w-full accent-foreground" />
                    </div>
                    <div>
                      <div className="mb-1 flex justify-between text-xs font-medium text-muted-foreground">
                        <span>Body X Position</span><span>{editingSlide.xRatioBody.toFixed(2)}</span>
                      </div>
                      <input type="range" min={0} max={1} step={0.01} value={editingSlide.xRatioBody}
                        onChange={(e) => setEditingSlide({ ...editingSlide, xRatioBody: Number(e.target.value) })}
                        className="w-full accent-foreground" />
                    </div>
                    <div>
                      <div className="mb-1 flex justify-between text-xs font-medium text-muted-foreground">
                        <span>Body Zoom (Scale)</span><span>{Math.round(editingSlide.scaleBody * 100)}%</span>
                      </div>
                      <input type="range" min={0.3} max={3} step={0.01} value={editingSlide.scaleBody}
                        onChange={(e) => setEditingSlide({ ...editingSlide, scaleBody: Number(e.target.value) })}
                        className="w-full accent-foreground" />
                    </div>
                  </>
                )}

                {editingSlide.slideType === "cta" && (
                  <>
                    <div>
                      <label className="mb-1 block text-xs font-medium text-muted-foreground">CTA Text</label>
                      <input value={editingSlide.ctaText}
                        onChange={(e) => setEditingSlide({ ...editingSlide, ctaText: e.target.value })}
                        className={inputClass} />
                    </div>
                    <div>
                      <div className="mb-1 flex justify-between text-xs font-medium text-muted-foreground">
                        <span>CTA Size</span><span>{editingSlide.fontSizeCta}px</span>
                      </div>
                      <input type="range" min={12} max={100} step={1} value={editingSlide.fontSizeCta}
                        onChange={(e) => setEditingSlide({ ...editingSlide, fontSizeCta: Number(e.target.value) })}
                        className="w-full accent-foreground" />
                    </div>
                    <div>
                      <div className="mb-1 flex justify-between text-xs font-medium text-muted-foreground">
                        <span>CTA Y Position</span><span>{editingSlide.yRatioCta.toFixed(2)}</span>
                      </div>
                      <input type="range" min={0} max={1} step={0.01} value={editingSlide.yRatioCta}
                        onChange={(e) => setEditingSlide({ ...editingSlide, yRatioCta: Number(e.target.value) })}
                        className="w-full accent-foreground" />
                    </div>
                    <div>
                      <div className="mb-1 flex justify-between text-xs font-medium text-muted-foreground">
                        <span>CTA X Position</span><span>{editingSlide.xRatioCta.toFixed(2)}</span>
                      </div>
                      <input type="range" min={0} max={1} step={0.01} value={editingSlide.xRatioCta}
                        onChange={(e) => setEditingSlide({ ...editingSlide, xRatioCta: Number(e.target.value) })}
                        className="w-full accent-foreground" />
                    </div>
                    <div>
                      <div className="mb-1 flex justify-between text-xs font-medium text-muted-foreground">
                        <span>CTA Zoom (Scale)</span><span>{Math.round(editingSlide.scaleCta * 100)}%</span>
                      </div>
                      <input type="range" min={0.3} max={3} step={0.01} value={editingSlide.scaleCta}
                        onChange={(e) => setEditingSlide({ ...editingSlide, scaleCta: Number(e.target.value) })}
                        className="w-full accent-foreground" />
                    </div>
                  </>
                )}
              </div>
            </div>

            <div className="flex shrink-0 gap-3 border-t border-border px-6 py-4">
              <button onClick={handleRegenerateSlide} disabled={regenerating}
                className="inline-flex flex-1 items-center justify-center gap-2 rounded-lg bg-foreground px-5 py-2.5 text-sm font-medium text-background transition-opacity hover:opacity-90 disabled:opacity-50">
                {regenerating ? <><Loader2 className="h-4 w-4 animate-spin" /> Regenerating...</> : <><RotateCcw className="h-4 w-4" /> Regenerate Slide</>}
              </button>
              <button onClick={() => setEditingSlide(null)}
                className="rounded-lg border border-border px-5 py-2.5 text-sm font-medium transition-colors hover:bg-muted">
                Cancel
              </button>
            </div>
          </div>
        </div>,
        document.body
      )}

      {/* Posting progress / results modal */}
      <PostingProgressModal
        open={postingModalOpen}
        results={postingResults}
        onClose={() => {
          setPostingModalOpen(false);
          setPostingResults(null);
          // Re-fetch on close so FailedOutputsSection always reflects DB state
          if (post?.id) {
            getFailedOutputs(post.id).then((fo) => setFailedOutputs(fo || [])).catch(() => {});
          }
        }}
      />

      {/* Image lightbox */}
      {expandedImage && typeof document !== "undefined" && createPortal(
        <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/85 backdrop-blur-sm cursor-pointer"
          onClick={() => setExpandedImage(null)}>
          <img src={expandedImage} alt="Expanded slide"
            className="max-h-[90vh] max-w-[90vw] rounded-lg object-contain shadow-2xl"
            onClick={(e) => e.stopPropagation()} />
          <button onClick={() => setExpandedImage(null)}
            className="absolute right-4 top-4 rounded-full bg-muted/80 p-2 text-foreground hover:bg-muted">
            <span className="text-xl leading-none">&times;</span>
          </button>
        </div>,
        document.body
      )}
    </div>
  );
}


