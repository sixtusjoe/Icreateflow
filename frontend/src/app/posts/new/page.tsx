"use client";

import { Suspense, useEffect, useState, useRef } from "react";
import { createPortal } from "react-dom";
import { useSearchParams } from "next/navigation";
import { toast } from "sonner";
import {
  Link2, Upload, Wand2, Download, Play, Clock,
  Image as ImageIcon, Type, Sparkles, Check, Loader2,
} from "lucide-react";
import {
  getBrands, importTikTokPost, uploadSlidesManually, getPost, updateSlide,
  uploadVariationImage, generateVariationImage, approveVariation,
  updateVariation, generatePost, getGenerationStatus,
  schedulePost, getMusicTracks, getDownloadUrl, fileUrl,
} from "@/lib/api";

type Step = "import" | "edit" | "variations" | "generate";

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
  const [postNumber, setPostNumber] = useState(1);
  const [importing, setImporting] = useState(false);
  const [manualFiles, setManualFiles] = useState<File[]>([]);
  const [manualCaption, setManualCaption] = useState("");

  const [post, setPost] = useState<any>(null);
  const [generating, setGenerating] = useState(false);
  const [genProgress, setGenProgress] = useState(0);
  const [scheduleTime, setScheduleTime] = useState("");
  const [selectedMusic, setSelectedMusic] = useState<number | null>(null);
  const [editLoaded, setEditLoaded] = useState(false);
  const [expandedImage, setExpandedImage] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<number>(0);

  useEffect(() => {
    getBrands().then(setBrands).catch(() => {});
    getMusicTracks().then(setMusicTracks).catch(() => {});
  }, []);

  useEffect(() => {
    if (editId && !editLoaded) {
      setEditLoaded(true);
      getPost(Number(editId))
        .then((data) => {
          setPost(data);
          setSelectedBrand(data.brand_id);
          setPostNumber(data.post_number || 1);
          if (data.scheduled_time) setScheduleTime(data.scheduled_time);
          if (data.music_track_id) setSelectedMusic(data.music_track_id);
          setStep("edit");
          toast.success("Post loaded");
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
      const result = await importTikTokPost({ tiktok_url: tiktokUrl, brand_id: selectedBrand, post_number: postNumber });
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
      const result = await uploadSlidesManually(selectedBrand, postNumber, manualCaption, manualFiles);
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

  const handleSlideUpdate = async (slideNum: number, field: string, value: string | boolean) => {
    if (!post) return;
    try { await updateSlide(post.id, slideNum, { [field]: value }); await reloadPost(); }
    catch { toast.error("Failed to update slide"); }
  };

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
      toast.success("Post scheduled!");
    } catch { toast.error("Failed to schedule"); }
  };

  const inputClass = "w-full rounded-lg border border-border bg-background px-4 py-2.5 text-sm outline-none transition-colors focus:border-foreground placeholder:text-muted-foreground";

  return (
    <div className="mx-auto max-w-5xl">
      <div className="mb-8">
        <h1 className="text-2xl font-bold tracking-tight">Create New Post</h1>
        <p className="mt-1 text-sm text-muted-foreground">Import slides, edit text, manage variations, and generate content.</p>
      </div>

      {/* Step Indicators */}
      <div className="mb-8 flex items-center gap-2">
        {(["import", "edit", "variations", "generate"] as Step[]).map((s, i) => (
          <div key={s} className="flex items-center gap-2">
            <button
              onClick={() => (post || s === "import") && setStep(s)}
              className={`flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
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
            {i < 3 && <div className="h-px w-8 bg-border" />}
          </div>
        ))}
      </div>

      {/* Step 1: Import */}
      {step === "import" && (
        <div className="rounded-2xl bg-card p-6">
          <div className="mb-5 flex gap-2">
            <button onClick={() => setImportMode("upload")}
              className={`flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
                importMode === "upload" ? "bg-foreground text-background" : "bg-muted text-muted-foreground hover:text-foreground"
              }`}>
              <Upload className="h-4 w-4" /> Upload Slides
            </button>
            <button onClick={() => setImportMode("tiktok")}
              className={`flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
                importMode === "tiktok" ? "bg-foreground text-background" : "bg-muted text-muted-foreground hover:text-foreground"
              }`}>
              <Link2 className="h-4 w-4" /> Import from TikTok
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

            <div>
              <label className="mb-1.5 block text-sm font-medium">Post Number (1-3 for the day)</label>
              <select defaultValue="1" onChange={(e) => e.target.value && setPostNumber(Number(e.target.value))}
                className="w-32 rounded-lg border border-border bg-background px-4 py-2.5 text-sm outline-none focus:border-foreground">
                <option value="1">Post 1</option>
                <option value="2">Post 2</option>
                <option value="3">Post 3</option>
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
                    className="w-full rounded-lg border border-border bg-background px-4 py-2.5 text-sm outline-none focus:border-foreground file:mr-3 file:border-0 file:bg-transparent file:text-sm file:font-medium" />
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
            <textarea value={post.caption || ""} onChange={(e) => setPost({ ...post, caption: e.target.value })}
              placeholder="Enter caption..." rows={2}
              className="w-full rounded-lg border border-border bg-background px-4 py-2.5 text-sm outline-none focus:border-foreground placeholder:text-muted-foreground resize-none" />
          </div>

          <h2 className="flex items-center gap-2 text-base font-semibold">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-foreground">
              <Type className="h-3.5 w-3.5 text-background" />
            </div>
            Slides (OCR-extracted text — review & edit)
          </h2>

          {post.slides?.map((slide: any) => (
            <div key={slide.id} className="rounded-2xl bg-card p-5">
              <div className="flex gap-4">
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

                <div className="flex-1 space-y-3">
                  <div className="flex items-center gap-3">
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
                      className="w-full rounded-lg border border-border bg-background px-4 py-2.5 text-sm outline-none focus:border-foreground placeholder:text-muted-foreground resize-none"
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

          <button onClick={() => setStep("variations")}
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
          <div className="flex gap-1 rounded-lg border border-border p-1">
            {post.brand?.accounts?.map((acc: any, idx: number) => (
              <button key={acc.id} onClick={() => setActiveTab(idx)}
                className={`flex-1 rounded-md px-4 py-2 text-sm font-medium transition-colors ${
                  activeTab === idx ? "bg-foreground text-background" : "text-muted-foreground hover:text-foreground"
                }`}>
                {acc.name}
                {acc.role === "master" && <span className="ml-1.5 text-[10px] opacity-60">master</span>}
              </button>
            ))}
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
                    <div key={slide.id} className="rounded-2xl bg-card p-5">
                      <div className="flex items-center gap-4">
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

                        <div className="flex-1">
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
                          <p className="text-sm text-muted-foreground">{slide.title_text}</p>
                        </div>

                        {acc.role !== "master" && (
                          <div className="flex flex-col gap-1.5">
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
          <div className="rounded-2xl bg-card p-6">
            <h2 className="mb-5 text-base font-semibold">Schedule & Music</h2>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="mb-1.5 block text-sm font-medium">Post Time</label>
                <input type="time" value={scheduleTime} onChange={(e) => setScheduleTime(e.target.value)} className={inputClass} />
                {selectedBrandData && (
                  <p className="mt-1.5 text-xs text-muted-foreground">
                    Timezone: {selectedBrandData.timezone} | Defaults: {selectedBrandData.default_post_times}
                  </p>
                )}
              </div>
              <div>
                <label className="mb-1.5 block text-sm font-medium">Background Music (for video version)</label>
                <select defaultValue="0" onChange={(e) => setSelectedMusic(e.target.value && e.target.value !== "0" ? Number(e.target.value) : null)}
                  className={inputClass}>
                  <option value="0">No music</option>
                  {musicTracks.map((t: any) => (
                    <option key={t.id} value={String(t.id)}>{t.name} {t.genre && `(${t.genre})`}</option>
                  ))}
                </select>
              </div>
            </div>
            <button onClick={handleSchedule}
              className="mt-4 inline-flex items-center gap-2 rounded-lg border border-border px-5 py-2.5 text-sm font-medium transition-colors hover:bg-muted">
              <Clock className="h-4 w-4" /> Save Schedule
            </button>
          </div>

          <div className="rounded-2xl bg-card p-6">
            <h2 className="mb-2 text-base font-semibold">Generate Content</h2>
            <p className="mb-5 text-sm text-muted-foreground">
              This will apply text overlays to all slides and create 9:16 videos with left transitions for all {post.brand?.accounts?.length || 5} accounts.
            </p>

            {generating && (
              <div className="mb-4">
                <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
                  <div className="h-full rounded-full bg-foreground transition-all duration-500" style={{ width: `${genProgress}%` }} />
                </div>
                <p className="mt-1.5 text-xs text-muted-foreground">Generating slides and videos...</p>
              </div>
            )}

            <button onClick={handleGenerate} disabled={generating}
              className="inline-flex items-center gap-2 rounded-lg bg-foreground px-5 py-2.5 text-sm font-medium text-background transition-opacity hover:opacity-90 disabled:opacity-50">
              {generating ? <><Loader2 className="h-4 w-4 animate-spin" /> Generating...</> : <><Play className="h-4 w-4" /> Generate All</>}
            </button>
          </div>

          {/* Downloads */}
          {post.outputs && post.outputs.length > 0 && (
            <div className="rounded-2xl bg-card p-6">
              <h2 className="mb-5 text-base font-semibold">Downloads</h2>
              <div className="space-y-2">
                {post.outputs.map((out: any) => {
                  const acc = post.brand?.accounts?.find((a: any) => a.id === out.account_id);
                  return (
                    <div key={out.id} className="flex items-center justify-between rounded-xl bg-muted/50 px-4 py-3">
                      <div className="flex items-center gap-3">
                        <span className="text-sm font-medium">{acc?.name || `Account ${out.account_id}`}</span>
                        <span className="rounded-full bg-muted px-2.5 py-0.5 text-xs font-medium capitalize">{out.posting_status}</span>
                      </div>
                      <a href={getDownloadUrl(post.id, out.account_id)}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted">
                        <Download className="h-3 w-3" /> Download ZIP
                      </a>
                    </div>
                  );
                })}
                <a href={getDownloadUrl(post.id)}
                  className="mt-2 inline-flex items-center gap-2 rounded-lg bg-foreground px-5 py-2.5 text-sm font-medium text-background transition-opacity hover:opacity-90">
                  <Download className="h-4 w-4" /> Download All
                </a>
              </div>
            </div>
          )}
        </div>
      )}

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
