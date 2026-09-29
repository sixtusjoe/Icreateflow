"use client";

/** The post editor — four steps, one page.
 *
 *  What the tables actually say, and what the page has to show because of it:
 *
 *    brands -> accounts(role: one master, any number of variations). An
 *    account carries FOUR handles, so an account is NOT a platform.
 *
 *    posts -> slides -> variations(slide x account) -> outputs(post x
 *    account), where the rendered files and the TikTok settings live.
 *
 *  Three rules the old page enforced without ever saying so:
 *    - the master posts the originals; its variations are not editable.
 *    - only variation accounts get a 3:4 slide set built for TikTok.
 *    - TikTok settings are per non-master account and gate Post Now.
 */

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { toast } from "sonner";
import {
  AlertCircle,
  ArrowRight,
  Check,
  ChevronDown,
  Clock,
  Copy,
  Download,
  Eye,
  FileText,
  Image as ImageIcon,
  Info,
  Play,
  Plus,
  RefreshCw,
  Send,
  Trash2,
  Type,
  Upload,
  Wand2,
} from "lucide-react";
import {
  approveVariation,
  deletePost,
  downloadFile,
  duplicatePost,
  fileUrl,
  generatePost,
  getBrands,
  getFailedOutputs,
  getGenerationStatus,
  getMusicTracks,
  getOutputSlides,
  getPost,
  importTikTokPost,
  postNow,
  regenerateVideo,
  rerunOcr,
  schedulePost,
  unschedulePost,
  updateSlide,
  uploadSlideImage,
  updateVariation,
  uploadSlidesManually,
  uploadVariationImage,
  updatePostMusic,
} from "@/lib/api";
import {
  Card,
  CardBody,
  CardHead,
  Chip,
  DotsMenu,
  Empty,
  PageActions,
  PageHead,
  PageTitle,
  PlatformIcon,
  PrimaryButton,
  Skeleton,
  Tabs,
  Tag,
  TwoCol,
  BackLink,
} from "@/components/kit";
import {
  ConfirmDialog,
  Dialog,
  DialogBody,
  DialogFoot,
  DialogHead,
  Field,
  GhostButton,
  Hint,
  Input,
  Textarea,
} from "@/components/kit/dialog";
import { apiErrorMessage } from "@/components/kit/format";
import { AiDialog, type AiTarget } from "@/components/post/ai-dialog";
import { FailedSection, type FailedOutput } from "@/components/post/failed";
import { Lightbox } from "@/components/post/lightbox";
import { PostingModal, type PostResult } from "@/components/post/posting";
import { SlideTextDialog, type EditableSlide } from "@/components/post/slide-text";
import { SlideImage } from "@/components/post/slide-image";
import { TikTokSetupCard, type OutputRow } from "@/components/post/tiktok-setup";

/** The three that get a rendered video. TikTok gets a photo set instead. */
const VIDEO_PLATFORMS = ["youtube", "instagram", "facebook"] as const;
type VideoPlatform = (typeof VIDEO_PLATFORMS)[number];
const PLAT_NAME: Record<string, string> = {
  tiktok: "TikTok",
  youtube: "YouTube",
  instagram: "Instagram",
  facebook: "Facebook",
};

const STEPS = ["Import", "Slides", "Variations", "Generate"] as const;

type Slide = {
  id: number;
  slide_number: number;
  type: string;
  title_text?: string | null;
  body_text?: string | null;
  cta_text?: string | null;
  master_image_path?: string | null;
  variations?: Variation[];
};
type Variation = {
  id: number;
  account_id: number;
  action: string;
  status: string;
  replacement_image_path?: string | null;
};
type Account = Record<string, unknown> & { id: number; name: string; role: string };
type Post = {
  id: number;
  brand_id: number;
  date: string;
  post_number: number;
  caption?: string | null;
  tiktok_url?: string | null;
  scheduled_time?: string | null;
  status: string;
  slides?: Slide[];
  outputs?: OutputRow[];
  brand?: { name: string; timezone?: string; default_post_times?: string; accounts?: Account[] };
};

export default function NewPostPage() {
  return (
    <Suspense fallback={<Skeleton className="h-[400px]" />}>
      <Editor />
    </Suspense>
  );
}

function Editor() {
  const params = useSearchParams();
  const editId = params.get("edit");

  const [post, setPost] = useState<Post | null>(null);
  const [step, setStep] = useState(editId ? 1 : 0);
  const [cacheKey, setCacheKey] = useState(0);
  const [zoom, setZoom] = useState<{ src: string; caption: string } | null>(null);
  const [ai, setAi] = useState<AiTarget | null>(null);
  const [failed, setFailed] = useState<FailedOutput[]>([]);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [confirmRebuild, setConfirmRebuild] = useState(false);
  const [confirmPost, setConfirmPost] = useState(false);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    if (!editId) return;
    try {
      const p = await getPost(Number(editId));
      setPost(p);
      setCacheKey((k) => k + 1);
      getFailedOutputs(p.id).then(setFailed).catch(() => {});
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not load that post"));
    }
  }, [editId]);

  useEffect(() => {
    // Fetching on mount. Every setState inside `reload` happens after an
    // await, so nothing here is synchronous — the rule cannot see that.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    reload();
  }, [reload]);

  const accounts = post?.brand?.accounts ?? [];
  const master = accounts.find((a) => a.role === "master");
  const slides = post?.slides ?? [];

  if (!editId && !post) return <ImportStep onCreated={(id) => (window.location.href = `/posts/new?edit=${id}`)} />;
  if (!post) return <Skeleton className="h-[420px]" />;

  const title = `${post.brand?.name ?? "Post"} #${post.post_number}`;
  const untitled = slides.filter((s) => !s.title_text?.trim()).length;
  const changed = countChanged(slides, accounts);
  // The consent stamp is the only proof the settings were saved rather
  // than merely typed, so it is what the rail reports on.
  const tiktokUnsaved = accounts.some(
    (a) =>
      a.role !== "master" &&
      !!a.tiktok_handle &&
      !(post.outputs ?? []).some((o) => o.account_id === a.id && o.tiktok_consent_at),
  );
  // Each step says what is outstanding on it, not just its name — and a
  // step with nothing left says so, which is what makes the rail worth
  // reading at a glance.
  const stepNotes = [
    post.tiktok_url ? `${slides.length} slides from TikTok` : `${slides.length} slides uploaded`,
    untitled ? `${untitled} have no title yet` : "Text read and checked",
    changed ? `${changed} of ${slides.length} changed` : "Every account posts the original",
    tiktokUnsaved
      ? "TikTok setup not saved"
      : post.scheduled_time
        ? `Goes out at ${post.scheduled_time.slice(0, 5)}`
        : "Build, then schedule",
  ];
  // A step is behind you once the one after it has something to show.
  const stepDone = [slides.length > 0, slides.length > 0 && !untitled, slides.length > 0, false];

  return (
    <>
      <BackLink href="/posts">Posts</BackLink>
      <PageHead>
        <PageTitle
          title={title}
          sub={
            <span className="flex flex-wrap items-center gap-2.5">
              <Tag tone={post.status === "scheduled" ? "live" : post.status === "failed" ? "stop" : "draft"}>
                {post.status.charAt(0).toUpperCase() + post.status.slice(1)}
              </Tag>
              <span className="inline-flex items-center gap-1.5 text-xs text-subtle">
                <FileText className="h-[13px] w-[13px]" />
                {post.brand?.name}
              </span>
              <span className="inline-flex items-center gap-1.5 text-xs text-subtle">
                <Clock className="h-[13px] w-[13px]" />
                {DAY.format(new Date(`${post.date}T00:00:00`))}
                {post.scheduled_time ? ` at ${post.scheduled_time.slice(0, 5)}` : ""}
              </span>
              <span className="inline-flex items-center gap-1.5 text-xs text-subtle">
                {slides.length} slides · {accounts.length} accounts
              </span>
            </span>
          }
        />
        <PageActions>
          <Chip icon={Eye} onClick={() => setStep(3)}>
            Preview
          </Chip>
          <Chip icon={Download} onClick={() => downloadFile(post.id).catch(() => toast.error("Nothing built yet"))}>
            Download
          </Chip>
          <DotsMenu
            label="Post actions"
            trigger={
              <span className="grid h-[34px] w-[34px] cursor-pointer place-items-center rounded-[11px] border border-border bg-card text-muted-foreground shadow-card transition-colors hover:bg-secondary hover:text-foreground">
                <ChevronDown className="h-[15px] w-[15px]" />
              </span>
            }
            items={[
              ...(post.status === "scheduled"
                ? [{ icon: Clock, label: "Move back to draft", onClick: () => unschedule(post.id, reload) }]
                : []),
              { icon: Copy, label: "Duplicate post", onClick: () => duplicate(post.id) },
              { icon: RefreshCw, label: "Read every slide again", onClick: () => runOcr(post.id, reload) },
              "-",
              { icon: Trash2, label: "Delete post", danger: true, onClick: () => setConfirmDelete(true) },
            ]}
          />
        </PageActions>
      </PageHead>

      <Card className="grid grid-cols-2 overflow-hidden lg:grid-cols-4">
        {STEPS.map((name, i) => (
          <button
            key={name}
            type="button"
            onClick={() => setStep(i)}
            className={`flex items-start gap-2.5 border-b border-r border-border px-4 py-3.5 text-left last:border-r-0 lg:border-b-0 ${
              step === i ? "bg-secondary" : "hover:bg-secondary"
            }`}
          >
            <span
              className={`mt-px grid h-[21px] w-[21px] flex-none place-items-center rounded-full text-[10.5px] font-bold ${
                step === i
                  ? "bg-primary text-primary-foreground"
                  : stepDone[i]
                    ? "bg-chart-1 text-[color:var(--lime-ink,#1a1f16)]"
                    : "bg-border text-muted-foreground"
              }`}
            >
              {stepDone[i] ? <Check className="h-[11px] w-[11px]" strokeWidth={3} /> : i + 1}
            </span>
            <span className="min-w-0">
              <span className={`block text-[12.5px] font-semibold ${step === i ? "text-foreground" : "text-muted-foreground"}`}>
                {name}
              </span>
              <span className="block truncate text-[11px] text-subtle">{stepNotes[i]}</span>
            </span>
          </button>
        ))}
      </Card>

      {step === 0 && <ImportStep onCreated={reload} inline onNext={() => setStep(1)} />}
      {step === 1 && <SlidesStep post={post} onChange={reload} onZoom={setZoom} onNext={() => setStep(2)} />}
      {step === 2 && (
        <VariationsStep
          post={post}
          accounts={accounts}
          cacheKey={cacheKey}
          onChange={reload}
          onZoom={setZoom}
          onAi={setAi}
          onNext={() => setStep(3)}
        />
      )}
      {step === 3 && (
        <GenerateStep
          post={post}
          accounts={accounts}
          master={master}
          failed={failed}
          cacheKey={cacheKey}
          onChange={reload}
          onZoom={setZoom}
          onRebuild={() => setConfirmRebuild(true)}
          onPostNow={() => setConfirmPost(true)}
        />
      )}

      <Lightbox src={zoom?.src ?? null} caption={zoom?.caption} onClose={() => setZoom(null)} />
      <AiDialog target={ai} onClose={() => setAi(null)} onDone={reload} />

      <ConfirmDialog
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        busy={busy}
        onConfirm={async () => {
          setBusy(true);
          try {
            await deletePost(post.id);
            toast.success("Post deleted");
            window.location.href = "/posts";
          } catch (e) {
            toast.error(apiErrorMessage(e, "Could not delete that post"));
            setBusy(false);
          }
        }}
        title="Delete post?"
        body="Everything this post is made of goes with it. This cannot be undone."
        bullets={[
          `Its ${slides.length} slides and all ${slides.length * accounts.length} account versions of them`,
          "Every rendered video and the TikTok slide set",
          ...(post.scheduled_time ? [`Its place in the schedule — nothing goes out at ${post.scheduled_time.slice(0, 5)}`] : []),
          "Anything already posted stays up on the platforms",
        ]}
        confirmLabel="Delete post"
      />

      <ConfirmDialog
        open={confirmRebuild}
        onClose={() => setConfirmRebuild(false)}
        busy={busy}
        onConfirm={async () => {
          setBusy(true);
          setConfirmRebuild(false);
          await build(post.id, reload);
          setBusy(false);
        }}
        title="Build it all again?"
        body="Every file this post has is rendered from scratch."
        bullets={[
          "The videos and the TikTok slides currently built",
          "Any single slide you re-positioned by hand after the last full build",
          "The slide text, every variation choice, the schedule, the music and the TikTok setup are all kept",
        ]}
        confirmLabel="Build it again"
      />

      {confirmPost && (
        <PostNowFlow
          post={post}
          accounts={accounts}
          master={master}
          onClose={() => {
            setConfirmPost(false);
            reload();
          }}
        />
      )}
    </>
  );
}

function countChanged(slides: Slide[], accounts: Account[]) {
  const variationIds = new Set(accounts.filter((a) => a.role !== "master").map((a) => a.id));
  return slides.reduce(
    (a, s) => a + (s.variations ?? []).filter((v) => variationIds.has(v.account_id) && v.action !== "keep").length,
    0,
  );
}

const DAY = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" });

/** A count inside a sentence is a word, not a figure. Figures are for the
 *  places that are counting — a stat tile, a column, a badge. */
const WORDS = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve"];
const spell = (n: number) => WORDS[n] ?? String(n);

/** "a, b and c" — joining with " and " throughout gives "a and b and c". */
const listOf = (parts: string[], joiner = "and") =>
  parts.length < 3
    ? parts.join(` ${joiner} `)
    : `${parts.slice(0, -1).join(", ")} ${joiner} ${parts[parts.length - 1]}`;

async function unschedule(postId: number, after: () => void) {
  try {
    await unschedulePost(postId);
    toast.success("Back to draft — nothing goes out now");
    after();
  } catch (e) {
    toast.error(apiErrorMessage(e, "Could not take it off the schedule"));
  }
}

async function duplicate(postId: number) {
  try {
    const copy = await duplicatePost(postId);
    toast.success("Duplicated as a draft");
    if (copy?.id) window.location.href = `/posts/new?edit=${copy.id}`;
  } catch (e) {
    toast.error(apiErrorMessage(e, "Could not duplicate that post"));
  }
}

async function runOcr(postId: number, after: () => void) {
  try {
    await rerunOcr(postId);
    toast.success("Read them all again");
    after();
  } catch (e) {
    toast.error(apiErrorMessage(e, "Could not re-read the slides"));
  }
}

async function build(postId: number, after: () => void) {
  try {
    await generatePost(postId);
    toast.success("Building — you can leave the page");
    const tick = setInterval(async () => {
      try {
        const s = await getGenerationStatus(postId);
        if (s?.status && s.status !== "generating") {
          clearInterval(tick);
          after();
        }
      } catch {
        clearInterval(tick);
      }
    }, 4000);
  } catch (e) {
    toast.error(apiErrorMessage(e, "Could not start the build"));
  }
}

/* ---------------------------------------------------------------- step 1 */

function ImportStep({
  onCreated,
  inline,
  onNext,
}: {
  onCreated: (id: number) => void;
  inline?: boolean;
  /** Present when the post already exists: the step's job is then to move
   *  on, not to import a second set of slides over the first. */
  onNext?: () => void;
}) {
  const [brands, setBrands] = useState<
    { id: number; name: string; accounts?: unknown[]; background_color?: string; timezone?: string }[]
  >([]);
  const [brand, setBrand] = useState<number | null>(null);
  const [mode, setMode] = useState("upload");
  const [url, setUrl] = useState("");
  const [caption, setCaption] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [audio, setAudio] = useState(true);
  const [audioName, setAudioName] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getBrands()
      .then((b) => {
        setBrands(b);
        if (b.length === 1) setBrand(b[0].id);
      })
      .catch(() => {});
  }, []);

  const go = async () => {
    if (!brand) return toast.error("Pick a brand first");
    setBusy(true);
    try {
      const made =
        mode === "tiktok"
          ? await importTikTokPost({ tiktok_url: url, brand_id: brand, import_audio: audio, audio_name: audioName })
          : await uploadSlidesManually(brand, caption, files);
      toast.success("Slides imported");
      onCreated(made.id ?? made.post_id);
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not import that"));
    } finally {
      setBusy(false);
    }
  };

  const body = (
    <Card>
      <CardHead title="Where the slides come from" sub="Pull a TikTok photo post apart, or upload the images yourself" flush={false} />
      <CardBody className="pt-0">
        <Tabs
          className="mb-3.5"
          value={mode}
          onChange={setMode}
          items={[
            { key: "upload", label: "Upload images" },
            { key: "tiktok", label: "Import from TikTok" },
          ]}
        />

        <div className="mb-2 text-[10.5px] font-bold uppercase leading-normal tracking-[0.09em] text-subtle">Brand</div>
        <div className="flex flex-wrap gap-2.5">
          {brands.map((b) => (
            <button
              key={b.id}
              type="button"
              onClick={() => setBrand(b.id)}
              aria-pressed={brand === b.id}
              className={`flex min-w-[232px] items-center gap-[11px] rounded-[13px] border py-[11px] pl-[11px] pr-3.5 text-left transition-colors ${
                brand === b.id ? "border-primary shadow-[0_0_0_1px_var(--color-primary)]" : "border-border hover:bg-secondary"
              }`}
            >
              <span
                className="grid h-[34px] w-[34px] flex-none place-items-center rounded-[10px] text-[15px] font-extrabold"
                style={{ background: b.background_color || "var(--secondary)", color: "#1a1f16" }}
              >
                {b.name.charAt(0).toUpperCase()}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-[13px] font-semibold leading-normal">{b.name}</span>
                <span className="block text-[11px] leading-normal text-subtle">
                  {(b.accounts ?? []).length} accounts{b.timezone ? ` · ${b.timezone}` : ""}
                </span>
              </span>
              {brand === b.id && <Check className="h-[15px] w-[15px] flex-none" />}
            </button>
          ))}
          <Link
            href="/brands"
            className="flex items-center gap-[7px] rounded-[13px] border border-dashed border-border py-[11px] pl-[11px] pr-3.5 text-[13px] font-semibold leading-normal text-subtle transition-colors hover:text-foreground"
          >
            <Plus className="h-[15px] w-[15px]" strokeWidth={2.2} />
            New brand
          </Link>
        </div>

        {mode === "upload" ? (
          <div className="mt-4">
            <label className="flex w-full cursor-pointer flex-col items-center gap-1.5 rounded-[14px] border border-dashed border-border bg-secondary px-5 py-[26px] transition-colors hover:border-subtle hover:bg-card">
              <input
                type="file"
                accept="image/*"
                multiple
                className="hidden"
                onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
              />
              <span className="grid h-[38px] w-[38px] place-items-center rounded-[11px] border border-border bg-card">
                <Upload className="h-[17px] w-[17px] text-subtle" strokeWidth={1.8} />
              </span>
              <span className="text-[13px] font-semibold leading-normal">
                {files.length ? (
                  `${files.length} images chosen`
                ) : (
                  <>
                    Drop the slide images here, or <b className="font-bold underline">browse</b>
                  </>
                )}
              </span>
              <span className="text-[11px] leading-normal text-subtle">In the order they should appear. PNG or JPEG.</span>
            </label>
            <div className="mt-3">
              <Field label="Caption">
                <Textarea
                  rows={2}
                  plain
                  value={caption}
                  onChange={(e) => setCaption(e.target.value)}
                  placeholder="Shared by every platform"
                />
              </Field>
            </div>
          </div>
        ) : (
          <div className="mt-4">
            <Field label="TikTok post URL">
              <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://www.tiktok.com/@user/photo/1234…" />
            </Field>
            <Hint>A photo post, not a video. The slides and the caption come across with it.</Hint>
            <div className="mt-3 rounded-[13px] border border-border bg-card px-3.5 py-3">
              <label className="flex cursor-pointer items-start gap-2.5">
                <input type="checkbox" checked={audio} onChange={(e) => setAudio(e.target.checked)} className="mt-0.5 h-4 w-4 accent-foreground" />
                <span>
                  <span className="block text-[13px] font-semibold leading-normal">Bring the audio across too</span>
                  <span className="block text-[11px] leading-[1.5] text-subtle">
                    Saved to your library and set as the track for the YouTube, Instagram and Facebook videos
                  </span>
                </span>
              </label>
              {audio && (
                <div className="mt-2.5">
                  <Field label="Call the track">
                    <Input
                      value={audioName}
                      onChange={(e) => setAudioName(e.target.value)}
                      placeholder="Left blank, it takes the name TikTok gives it"
                    />
                  </Field>
                </div>
              )}
            </div>
          </div>
        )}

      </CardBody>
    </Card>
  );

  const foot = (
    <div className="mt-4 flex items-center justify-end gap-2.5">
      {onNext && (
        <GhostButton onClick={go} disabled={busy || !brand || (mode === "tiktok" ? !url.trim() : !files.length)}>
          {busy ? "Importing…" : "Replace the slides"}
        </GhostButton>
      )}
      {onNext ? (
        <PrimaryButton icon={ArrowRight} iconRight onClick={onNext}>
          Next: the slide text
        </PrimaryButton>
      ) : (
        <PrimaryButton
          icon={ArrowRight}
          iconRight
          onClick={go}
          disabled={busy || !brand || (mode === "tiktok" ? !url.trim() : !files.length)}
        >
          {busy ? "Importing…" : "Import the slides"}
        </PrimaryButton>
      )}
    </div>
  );

  if (inline)
    return (
      <>
        {body}
        {foot}
      </>
    );
  return (
    <>
      <BackLink href="/posts">Posts</BackLink>
      <PageHead>
        <PageTitle title="New post" sub="A post is a stack of slides for one brand on one day." />
      </PageHead>
      {body}
      {foot}
    </>
  );
}

/* ---------------------------------------------------------------- step 2 */

function SlidesStep({
  post,
  onChange,
  onZoom,
  onNext,
}: {
  post: Post;
  onChange: () => void;
  onZoom: (z: { src: string; caption: string }) => void;
  onNext: () => void;
}) {
  const [caption, setCaption] = useState(post.caption ?? "");

  const saveCaption = async () => {
    try {
      await schedulePost(post.id, { caption });
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not save the caption"));
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHead
          title="Caption"
          sub="One caption, used by every platform"
          right={
            <DotsMenu
              label="Caption options"
              items={[
                {
                  icon: Copy,
                  label: "Copy caption",
                  onClick: () => {
                    navigator.clipboard?.writeText(caption).then(
                      () => toast.success("Caption copied"),
                      () => toast.error("Could not copy it"),
                    );
                  },
                },
              ]}
            />
          }
        />
        <CardBody className="pt-3">
          <Textarea rows={2} plain value={caption} onChange={(e) => setCaption(e.target.value)} onBlur={saveCaption} />
        </CardBody>
      </Card>

      <div className="flex items-end justify-between gap-3 px-0.5 pt-1">
        <div>
          <div className="text-[14.5px] font-bold leading-normal">Slides</div>
          <div className="mt-px text-[11.5px] leading-normal text-subtle">
            The text was read off the images — check it before anything is built, because this is what gets burned into
            the video
          </div>
        </div>
        <Chip icon={RefreshCw} onClick={() => runOcr(post.id, onChange)}>
          Read them all again
        </Chip>
      </div>

      {(post.slides ?? []).map((s) => (
        <SlideCard key={s.id} post={post} slide={s} onChange={onChange} onZoom={onZoom} />
      ))}

      <div className="flex justify-end">
        <PrimaryButton icon={ArrowRight} iconRight onClick={onNext}>
          Next: a version per account
        </PrimaryButton>
      </div>
    </div>
  );
}

/** The preview's `.segs` — a small three-way switch inside a field row.
 *  A native select here reads as a form control among form controls; this
 *  reads as the thing being switched. */
function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { key: T; label: string }[];
  onChange: (k: T) => void;
  label: string;
}) {
  return (
    <span role="group" aria-label={label} className="inline-flex gap-0.5 rounded-[9px] border border-border bg-secondary p-0.5">
      {options.map((o) => {
        const on = o.key === value;
        return (
          <button
            key={o.key}
            type="button"
            onClick={() => onChange(o.key)}
            aria-pressed={on}
            className={`rounded-[7px] px-[9px] py-1 text-[11.5px] font-semibold leading-normal transition-colors ${
              on ? "bg-card text-foreground shadow-[0_1px_2px_rgba(16,24,40,0.12)]" : "text-subtle hover:text-foreground"
            }`}
          >
            {o.label}
          </button>
        );
      })}
    </span>
  );
}

/** The slide-number pill is coloured by what the slide is for: a hook
 *  leads, a CTA closes, the rest are the middle. */
function TypeTag({ type, children }: { type: string; children: React.ReactNode }) {
  const tone =
    type === "hook"
      ? "bg-primary text-primary-foreground"
      : type === "cta"
        ? "bg-[rgba(74,58,167,0.12)] text-[#4A3AA7] dark:text-[#A99CF5]"
        : "border border-border bg-secondary text-muted-foreground";
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-bold leading-none ${tone}`}>
      {children}
    </span>
  );
}

function SlideCard({
  post,
  slide,
  onChange,
  onZoom,
}: {
  post: Post;
  slide: Slide;
  onChange: () => void;
  onZoom: (z: { src: string; caption: string }) => void;
}) {
  const [title, setTitle] = useState(slide.title_text ?? "");
  const [body, setBody] = useState(slide.body_text ?? "");
  const [cta, setCta] = useState(slide.cta_text ?? "");
  const fileInput = useRef<HTMLInputElement>(null);

  const save = async (field: string, value: string) => {
    try {
      await updateSlide(post.id, slide.slide_number, { [field]: value });
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not save that"));
    }
  };

  const img = slide.master_image_path ? fileUrl(slide.master_image_path) : null;

  return (
    <Card>
      <div className="flex gap-4 px-[18px] py-4">
        <button
          type="button"
          onClick={() => img && onZoom({ src: img, caption: `Slide ${slide.slide_number} · the original` })}
          className="h-[118px] w-[88px] flex-none overflow-hidden rounded-[12px] border border-border bg-secondary"
          aria-label={`See slide ${slide.slide_number} full size`}
        >
          <SlideImage src={img} label={slide.slide_number} />
        </button>

        <div className="flex min-w-0 flex-1 flex-col gap-2.5">
          <div className="flex flex-wrap items-center gap-2.5">
            <TypeTag type={slide.type}>Slide {slide.slide_number}</TypeTag>
            <Segmented
              label={`Slide ${slide.slide_number} type`}
              value={slide.type}
              onChange={(k) => save("type", k).then(onChange)}
              options={[
                { key: "hook", label: "Hook" },
                { key: "content", label: "Content" },
                { key: "cta", label: "CTA" },
              ]}
            />
            <span className="ml-auto">
              <DotsMenu
                label={`Slide ${slide.slide_number} actions`}
                items={[
                  { icon: RefreshCw, label: "Read this one again", onClick: () => runOcr(post.id, onChange) },
                  { icon: Upload, label: "Replace the image", onClick: () => fileInput.current?.click() },
                ]}
              />
            </span>
          </div>
          <input
            ref={fileInput}
            type="file"
            accept="image/*"
            className="hidden"
            onChange={async (e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (!f) return;
              try {
                await uploadSlideImage(post.id, slide.slide_number, f);
                toast.success("Image replaced");
                onChange();
              } catch (err) {
                toast.error(apiErrorMessage(err, "Could not replace that image"));
              }
            }}
          />

          <Field
            label={
              <span>
                Title
                {!title.trim() && <em className="ml-1 font-normal not-italic text-subtle">— nothing was read off this slide</em>}
              </span>
            }
          >
            <Input value={title} onChange={(e) => setTitle(e.target.value)} onBlur={() => save("title_text", title)} placeholder="Type what should sit at the top" />
          </Field>
          <Field label="Body">
            <Textarea rows={2} plain value={body} onChange={(e) => setBody(e.target.value)} onBlur={() => save("body_text", body)} />
          </Field>
          {slide.type === "cta" && (
            <Field label="Call to action">
              <Input value={cta} onChange={(e) => setCta(e.target.value)} onBlur={() => save("cta_text", cta)} />
            </Field>
          )}
        </div>
      </div>
    </Card>
  );
}

/* ---------------------------------------------------------------- step 3 */

function VariationsStep({
  post,
  accounts,
  cacheKey,
  onChange,
  onZoom,
  onAi,
  onNext,
}: {
  post: Post;
  accounts: Account[];
  cacheKey: number;
  onChange: () => void;
  onZoom: (z: { src: string; caption: string }) => void;
  onAi: (t: AiTarget) => void;
  onNext: () => void;
}) {
  const [active, setActive] = useState(() => accounts.find((a) => a.role !== "master")?.id ?? accounts[0]?.id ?? 0);
  const account = accounts.find((a) => a.id === active);
  const slides = post.slides ?? [];
  const isMaster = account?.role === "master";
  const [bulking, setBulking] = useState(false);
  // The master leads — it is the one the others are varied from. Ordering
  // by which tab is open would move the strip under the operator's hand.
  const ordered = [...accounts].sort((x, y) => Number(y.role === "master") - Number(x.role === "master"));

  const varsFor = (accountId: number) =>
    slides.map((sl) => (sl.variations ?? []).find((v) => v.account_id === accountId)).filter(Boolean) as Variation[];
  const mine = varsFor(active);
  const changedHere = mine.filter((v) => v.action !== "keep").length;
  const waitingHere = mine.filter((v) => v.status === "generated").length;
  const originals = mine.filter((v) => v.action === "keep");

  /** Both bulk actions are the same shape: walk this account's variations
   *  and apply one call to each, then reload once. */
  const bulk = async (rows: Variation[], fn: (v: Variation) => Promise<unknown>, done: string) => {
    if (!rows.length) return;
    setBulking(true);
    try {
      for (const v of rows) await fn(v);
      toast.success(done);
      onChange();
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not apply that to every slide"));
    } finally {
      setBulking(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="px-0.5">
        <div className="text-[14.5px] font-bold leading-normal">A version per account</div>
        <div className="mt-px max-w-[82ch] text-[11.5px] leading-[1.55] text-subtle">
          {post.brand?.name} posts from {accounts.length} accounts. Sending the same images from all of them is the
          pattern a platform looks for, so every account after the master gets its own copy of each slide — same words,
          different picture.
        </div>
      </div>

      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
        {ordered.map((a) => {
          const changed = slides.filter((s) =>
            (s.variations ?? []).some((v) => v.account_id === a.id && v.action !== "keep"),
          ).length;
          return (
            <button
              key={a.id}
              type="button"
              onClick={() => setActive(a.id)}
              aria-pressed={a.id === active}
              className={`flex items-center gap-2.5 rounded-[14px] border bg-card px-3.5 py-3 text-left shadow-card transition-colors ${
                a.id === active ? "border-primary shadow-[0_0_0_1px_var(--color-primary)]" : "border-border hover:bg-secondary"
              }`}
            >
              <span className="min-w-0 flex-1">
                <span className="block text-[13px] font-semibold leading-normal">{a.name}</span>
                <span className="block text-[11px] leading-normal text-subtle">
                  {a.role === "master" ? "posts the originals" : `${changed} of ${slides.length} changed`}
                </span>
              </span>
              <span className="flex flex-none gap-1.5 text-subtle">
                {(["tiktok", "instagram", "youtube", "facebook"] as const)
                  .filter((p) => a[`${p}_handle`] && !(a.role === "master" && p === "tiktok"))
                  .map((p) => (
                    <PlatformIcon key={p} platform={p} className="h-3.5 w-3.5" />
                  ))}
              </span>
            </button>
          );
        })}
      </div>

      {!isMaster && (
        <div className="flex flex-wrap items-center gap-2 px-0.5">
          <span className="text-[11.5px] leading-normal text-muted-foreground">
            <b className="font-bold text-foreground">{changedHere}</b> of {slides.length} slides changed ·{" "}
            {waitingHere ? `${waitingHere} waiting on you` : "none waiting on you"}
          </span>
          <span className="ml-auto flex flex-wrap items-center gap-2">
            {originals.length > 0 && (
              <Chip
                icon={Wand2}
                onClick={() =>
                  bulk(
                    originals,
                    (v) => updateVariation(v.id, "generate"),
                    `Queued ${originals.length} slides for AI`,
                  )
                }
              >
                {bulking ? "Working…" : `AI for the ${spell(originals.length)} originals`}
              </Chip>
            )}
            {changedHere > 0 && (
              <Chip
                icon={RefreshCw}
                onClick={() =>
                  bulk(
                    mine.filter((v) => v.action !== "keep"),
                    (v) => updateVariation(v.id, "keep"),
                    "Back to the originals",
                  )
                }
              >
                Back to originals
              </Chip>
            )}
          </span>
        </div>
      )}

      {isMaster ? (
        <Card>
          <CardBody className="pt-5">
            <div className="flex items-start gap-3">
              <span className="grid h-[34px] w-[34px] flex-none place-items-center rounded-[11px] border border-border bg-secondary text-subtle">
                <Check className="h-4 w-4" />
              </span>
              <div>
                <div className="text-[14.5px] font-bold leading-normal">{account?.name} posts the originals</div>
                <div className="mt-px max-w-[80ch] text-[11.5px] leading-[1.55] text-subtle">
                  The master account is the one everything else is varied from, so there is nothing to choose here. Edit
                  a slide on the Slides step and it changes for this account too.
                </div>
              </div>
            </div>
            <div className="mt-4 flex flex-wrap gap-2.5">
              {slides.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  onClick={() =>
                    s.master_image_path &&
                    onZoom({ src: fileUrl(s.master_image_path), caption: `Slide ${s.slide_number} · the original` })
                  }
                  className="h-[83px] w-[62px] overflow-hidden rounded-[11px] border border-border bg-secondary"
                  aria-label={`See slide ${s.slide_number} full size`}
                >
                  <SlideImage
                    src={s.master_image_path ? fileUrl(s.master_image_path) : null}
                    label={s.slide_number}
                  />
                </button>
              ))}
            </div>
            <Hint>The master also skips TikTok — only the variation accounts get a 3:4 slide set built for it.</Hint>
          </CardBody>
        </Card>
      ) : (
        slides.map((s) => {
          const v = (s.variations ?? []).find((x) => x.account_id === active);
          if (!v) return null;
          return (
            <VariationRow
              key={s.id}
              slide={s}
              variation={v}
              accountName={account?.name ?? ""}
              cacheKey={cacheKey}
              onChange={onChange}
              onZoom={onZoom}
              onAi={onAi}
            />
          );
        })
      )}

      <div className="flex justify-end">
        <PrimaryButton icon={ArrowRight} iconRight onClick={onNext}>
          Next: build and schedule
        </PrimaryButton>
      </div>
    </div>
  );
}

function VariationRow({
  slide,
  variation,
  accountName,
  cacheKey,
  onChange,
  onZoom,
  onAi,
}: {
  slide: Slide;
  variation: Variation;
  accountName: string;
  cacheKey: number;
  onChange: () => void;
  onZoom: (z: { src: string; caption: string }) => void;
  onAi: (t: AiTarget) => void;
}) {
  const replacement = variation.replacement_image_path
    ? `${fileUrl(variation.replacement_image_path)}?v=${cacheKey}`
    : null;
  const original = slide.master_image_path ? fileUrl(slide.master_image_path) : null;
  const pick = variation.action === "keep" ? "keep" : variation.action === "generate" ? "ai" : "own";
  const waiting = variation.status === "generated";

  const upload = () => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "image/*";
    input.onchange = async () => {
      const f = input.files?.[0];
      if (!f) return;
      try {
        await uploadVariationImage(variation.id, f);
        toast.success("Image uploaded");
        onChange();
      } catch (e) {
        toast.error(apiErrorMessage(e, "Could not upload that image"));
      }
    };
    input.click();
  };

  const keep = async () => {
    try {
      await updateVariation(variation.id, "keep");
      onChange();
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not reset that slide"));
    }
  };

  const approve = async () => {
    try {
      await approveVariation(variation.id);
      toast.success("Approved");
      onChange();
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not approve that"));
    }
  };

  const text = slide.title_text?.trim() || slide.body_text?.trim() || "";

  return (
    <Card className="flex flex-wrap items-center gap-4 px-[18px] py-3.5">
      <div className="flex flex-none items-center gap-2.5">
        <Thumb
          src={original}
          label={slide.slide_number}
          onClick={() => original && onZoom({ src: original, caption: `Slide ${slide.slide_number} · the original` })}
        />
        <ArrowRight className="h-3.5 w-3.5 flex-none text-subtle" />
        {replacement ? (
          <Thumb
            src={replacement}
            label={slide.slide_number}
            onClick={() => onZoom({ src: replacement, caption: `Slide ${slide.slide_number} · ${accountName}` })}
          />
        ) : (
          <span className="grid h-[83px] w-[62px] flex-none place-items-center rounded-[11px] border border-dashed border-border text-[9.5px] font-semibold text-subtle">
            Same image
          </span>
        )}
      </div>

      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <div className="flex flex-wrap items-center gap-2.5">
          <TypeTag type={slide.type}>Slide {slide.slide_number}</TypeTag>
          <Tag tone={pick === "keep" ? "draft" : pick === "own" ? "done" : waiting ? "skip" : "live"}>
            {pick === "keep" ? "Original" : pick === "own" ? "Your image" : waiting ? "AI made · waiting on you" : "AI made · approved"}
          </Tag>
        </div>
        {/* Title then body, always both lines — the pair is how you tell one
            slide from the next when six of them share a picture. */}
        <div
          className={`truncate text-[13px] leading-normal ${
            slide.title_text?.trim() ? "font-semibold" : "italic text-subtle"
          }`}
        >
          {slide.title_text?.trim() || "No title on this slide"}
        </div>
        {slide.body_text?.trim() && (
          <div className="truncate text-[11.5px] leading-[1.45] text-subtle">{slide.body_text}</div>
        )}
      </div>

      <div className="flex flex-none flex-col items-end gap-2">
        <div className="flex items-center gap-[2px] rounded-[10px] border border-border bg-secondary p-[2px]">
          {(
            [
              { key: "keep", label: "Original", icon: Check, act: keep },
              { key: "own", label: "Upload", icon: Upload, act: upload },
              {
                key: "ai",
                label: "AI",
                icon: Wand2,
                act: () =>
                  onAi({
                    variationId: variation.id,
                    slideNumber: slide.slide_number,
                    accountName,
                    text,
                    imageUrl: original ?? undefined,
                    mode: "make",
                  }),
              },
            ] as const
          ).map((o) => {
            const Icon = o.icon;
            return (
              <button
                key={o.key}
                type="button"
                onClick={o.act}
                aria-pressed={pick === o.key}
                className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-[8px] px-2.5 py-[5px] text-[11.5px] font-semibold leading-normal transition-colors ${
                  pick === o.key ? "bg-card text-foreground shadow-card" : "text-subtle hover:text-foreground"
                }`}
              >
                <Icon className="h-3 w-3" />
                {o.label}
              </button>
            );
          })}
        </div>
        <div className="flex gap-2">
          {replacement && pick === "ai" && (
            <Chip
              icon={RefreshCw}
              onClick={() =>
                onAi({
                  variationId: variation.id,
                  slideNumber: slide.slide_number,
                  accountName,
                  text,
                  imageUrl: replacement,
                  mode: "edit",
                })
              }
            >
              Change it
            </Chip>
          )}
          {waiting && (
            <PrimaryButton icon={Check} onClick={approve} className="px-3 py-[7px] text-[11.5px]">
              Approve
            </PrimaryButton>
          )}
        </div>
      </div>
    </Card>
  );
}

function Thumb({ src, label, onClick }: { src: string | null; label: number; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={`See slide ${label} full size`}
      className="h-[83px] w-[62px] flex-none overflow-hidden rounded-[11px] border border-border bg-secondary"
    >
      <SlideImage src={src} label={label} />
    </button>
  );
}

/* ---------------------------------------------------------------- step 4 */

function GenerateStep({
  post,
  accounts,
  master,
  failed,
  cacheKey,
  onChange,
  onZoom,
  onRebuild,
  onPostNow,
}: {
  post: Post;
  accounts: Account[];
  master?: Account;
  failed: FailedOutput[];
  cacheKey: number;
  onChange: () => void;
  onZoom: (z: { src: string; caption: string }) => void;
  onRebuild: () => void;
  onPostNow: () => void;
}) {
  const [validity, setValidity] = useState<Record<string, boolean>>({});
  const [time, setTime] = useState(post.scheduled_time?.slice(0, 5) ?? "");
  const [savingTime, setSavingTime] = useState(false);
  const [previews, setPreviews] = useState<Record<string, unknown>[] | null>(null);
  const [previewAccount, setPreviewAccount] = useState(0);
  const [platform, setPlatform] = useState<VideoPlatform>("youtube");
  const [editing, setEditing] = useState<{ accountId: number; name: string; index: number } | null>(null);
  const [tracks, setTracks] = useState<{ id: number; name: string; platforms_allowed?: string | null }[]>([]);
  const [music, setMusic] = useState<Record<VideoPlatform, number | null>>({
    youtube: (post as unknown as Record<string, number | null>).youtube_music_track_id ?? null,
    instagram: (post as unknown as Record<string, number | null>).instagram_music_track_id ?? null,
    facebook: (post as unknown as Record<string, number | null>).facebook_music_track_id ?? null,
  });

  useEffect(() => {
    getMusicTracks().then(setTracks).catch(() => {});
  }, []);

  const onValidity = useCallback((key: string, ok: boolean) => setValidity((v) => ({ ...v, [key]: ok })), []);

  // The master posts the originals and skips TikTok entirely. Every other
  // account with a TikTok handle needs its own settings for this post —
  // whether or not it is signed in yet, and whether or not the files have
  // been built. TikTok has no account-wide default to fall back on.
  const tiktokCards = accounts
    .filter((a) => a.role !== "master" && !!a.tiktok_handle)
    .map((a) => ({
      account: a,
      output: (post.outputs ?? []).find((o) => o.account_id === a.id) ?? null,
    }));
  const gated = tiktokCards.some((c) => !validity[`acct:${c.account.id}`]);
  // A video is only rendered for a platform some account can actually post
  // to. Counting all three would promise files that are never made.
  const linkedVideoPlatforms = VIDEO_PLATFORMS.filter((p) => accounts.some((a) => a[`${p}_token`]));
  const unlinkedVideoPlatforms = VIDEO_PLATFORMS.filter((p) => !accounts.some((a) => a[`${p}_token`]));
  // An output row is not a build. TikTok's settings create a row before
  // anything is rendered, so "built" has to mean a row that points at
  // files — otherwise saving a privacy setting makes the page claim the
  // videos exist.
  // `files_on_disk` is the server's own stat of the rendered paths. A row
  // survives a cleared output directory; the files are what a post sends.
  const built = (post.outputs ?? []).some((o) => o.files_on_disk);
  const recordOnly = !built && (post.outputs ?? []).some((o) => o.video_path || o.slides_dir);
  // A platform with no token is skipped silently, so a post with none of them
  // connected has nowhere to go. Say that rather than letting it "succeed".
  const reachable = accounts.reduce(
    (count, a) =>
      count +
      (["tiktok", "instagram", "youtube", "facebook"] as const).filter(
        (pl) => a[`${pl}_token`] && !(a.role === "master" && pl === "tiktok"),
      ).length,
    0,
  );

  const saveTime = async () => {
    setSavingTime(true);
    try {
      await schedulePost(post.id, { scheduled_time: time });
      toast.success("Schedule saved");
      onChange();
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not save the schedule"));
    } finally {
      setSavingTime(false);
    }
  };

  const saveMusic = async (p: VideoPlatform, id: number | null) => {
    setMusic((m) => ({ ...m, [p]: id }));
    try {
      await updatePostMusic(post.id, { [`${p}_music_track_id`]: id });
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not set that track"));
    }
  };

  const slidesFor = (post.slides ?? []).map<EditableSlide>((s) => ({
    slide_number: s.slide_number,
    type: s.type,
    title_text: s.title_text,
    body_text: s.body_text,
    cta_text: s.cta_text,
    imageUrl: s.master_image_path ? fileUrl(s.master_image_path) : undefined,
  }));

  const current = previews?.[previewAccount] as
    | { account_id: number; account_name: string; account_role: string; slides_3x4?: string[]; [k: string]: unknown }
    | undefined;

  return (
    <>
      {failed.length > 0 && (
        <FailedSection postId={post.id} outputs={failed} onChange={onChange} />
      )}
      {post.status === "failed" && failed.length === 0 && (
        <div className="flex items-start gap-3 rounded-[16px] border border-destructive/30 bg-destructive/[0.07] px-4 py-3.5">
          <span className="grid h-[31px] w-[31px] flex-none place-items-center rounded-[10px] bg-destructive/15 text-destructive">
            <AlertCircle className="h-[15px] w-[15px]" />
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-[13px] font-bold leading-normal text-destructive">This post failed to publish</div>
            <div className="mt-0.5 max-w-[70ch] text-[11px] leading-[1.5] text-subtle">
              No per-platform detail was stored for it — either it failed before we started recording them, or the detail
              has been cleared. Post it again to find out why.
            </div>
          </div>
        </div>
      )}

      <TwoCol
        main={
          <div className="flex flex-col gap-4">
            <Card>
              <CardHead
                title="Build the files"
                sub="Burns the text onto every slide, then renders one 9:16 video per platform per account"
                right={
                  <DotsMenu
                    label="Build options"
                    items={[
                      {
                        icon: Download,
                        label: "Download everything",
                        onClick: () => downloadFile(post.id).catch(() => toast.error("Nothing built yet")),
                      },
                      { icon: RefreshCw, label: "Build it all again", onClick: onRebuild },
                    ]}
                  />
                }
              />
              <CardBody className="pt-0">
                <div className="mb-4 grid grid-cols-1 gap-2.5 sm:grid-cols-3">
                  <Stat n={accounts.length} label="accounts" />
                  <Stat
                    n={(post.slides ?? []).length}
                    label="TikTok slides"
                    note={accounts.filter((a) => a.role !== "master").map((a) => a.name).join(", ") || "variation accounts only"}
                  />
                  <Stat
                    n={accounts.length * linkedVideoPlatforms.length}
                    label="videos"
                    note={
                      linkedVideoPlatforms.length
                        ? `${accounts.length} accounts × ${linkedVideoPlatforms.map((p) => PLAT_NAME[p]).join(", ")}`
                        : "no video platform is linked"
                    }
                  />
                </div>
                <div className="flex flex-wrap items-center gap-2.5">
                  {built ? (
                    <>
                      <span className="grid h-[26px] w-[26px] flex-none place-items-center rounded-full bg-good/15 text-good">
                        <Check className="h-3.5 w-3.5" strokeWidth={3} />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-[13px] font-semibold leading-normal">Everything is built</span>
                        <span className="block text-[11px] leading-normal text-subtle">
                          {(post.outputs ?? []).length} account outputs ready
                        </span>
                      </span>
                      <Chip icon={RefreshCw} onClick={onRebuild}>
                        Build it all again
                      </Chip>
                    </>
                  ) : recordOnly ? (
                    <>
                      <span className="grid h-[26px] w-[26px] flex-none place-items-center rounded-full bg-bad/15 text-bad">
                        <AlertCircle className="h-3.5 w-3.5" />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-[13px] font-semibold leading-normal">The built files are gone</span>
                        <span className="block text-[11px] leading-normal text-subtle">
                          This post was built before, but the rendered files are no longer on disk
                        </span>
                      </span>
                      <PrimaryButton icon={Play} onClick={onRebuild}>
                        Build it again
                      </PrimaryButton>
                    </>
                  ) : (
                    <PrimaryButton icon={Play} onClick={onRebuild}>
                      Build it
                    </PrimaryButton>
                  )}
                </div>
                {unlinkedVideoPlatforms.length > 0 && (
                  <Hint>
                    {listOf(unlinkedVideoPlatforms.map((p) => PLAT_NAME[p]))}{" "}
                    {unlinkedVideoPlatforms.length === 1 ? "is" : "are"} not linked on any account, so no{" "}
                    {listOf(unlinkedVideoPlatforms.map((p) => PLAT_NAME[p]), "or")} video is built and nothing goes out
                    there.
                  </Hint>
                )}
                <Hint>Takes a couple of minutes. You can leave the page — it keeps going.</Hint>
              </CardBody>
            </Card>

            {tiktokCards.length > 0 && (
              <Card>
                <CardHead
                  title="TikTok setup"
                  sub="TikTok has no default for privacy or disclosure and no account-wide setting — it has to be chosen, and saved, for every post"
                  right={
                    <DotsMenu
                      label="TikTok setup options"
                      items={[
                        {
                          icon: FileText,
                          label: "TikTok's posting rules",
                          href: "https://developers.tiktok.com/doc/content-sharing-guidelines",
                        },
                      ]}
                    />
                  }
                />
                <CardBody className="pt-3">
                  <div className="flex flex-col gap-2.5">
                    {tiktokCards.map(({ account: a, output }) => (
                      <TikTokSetupCard
                        key={a.id}
                        output={output}
                        postId={post.id}
                        accountId={a.id}
                        accountName={a.name}
                        handle={a.tiktok_handle as string | null}
                        connected={!!a.tiktok_token}
                        onValidity={onValidity}
                      />
                    ))}
                  </div>
                  <Hint>
                    {tiktokCards.length === 1 ? (
                      <>
                        Only <b>{tiktokCards[0].account.name}</b> needs this.
                      </>
                    ) : (
                      <>
                        <b>{tiktokCards.map((c) => c.account.name).join(", ")}</b> each need their own.
                      </>
                    )}
                    {master ? ` ${master.name} is the master, and the master does not post to TikTok.` : ""}
                  </Hint>
                </CardBody>
              </Card>
            )}

            <Card>
              <CardHead
                title="Preview"
                sub="What each account will actually post"
                right={
                  <DotsMenu
                    label="Preview options"
                    items={[
                      {
                        icon: Download,
                        label: "Download this account",
                        onClick: () =>
                          downloadFile(post.id, Number(current?.account_id)).catch(() =>
                            toast.error("Nothing to download"),
                          ),
                      },
                      {
                        icon: RefreshCw,
                        label: "Rebuild this account",
                        onClick: () =>
                          regenerateVideo(post.id, Number(current?.account_id), platform)
                            .then(() => {
                              toast.success("Rebuilding");
                              onChange();
                            })
                            .catch((e) => toast.error(apiErrorMessage(e, "Could not rebuild that"))),
                      },
                    ]}
                  />
                }
              />
              <CardBody className="pt-3">
                {!previews ? (
                  <div className="flex items-center gap-3 rounded-[14px] border border-dashed border-border bg-secondary px-3.5 py-3.5">
                    <span className="grid h-[31px] w-[31px] flex-none place-items-center rounded-[10px] border border-border bg-card text-subtle">
                      <Eye className="h-[15px] w-[15px]" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="text-[13px] font-semibold leading-normal">Previews are not loaded yet</div>
                      <div className="text-[11px] leading-[1.45] text-subtle">
                        The slides and videos, fetched only when you ask for them — they are the heaviest thing on this
                        page
                      </div>
                    </div>
                    <Chip
                      icon={Eye}
                      onClick={() =>
                        getOutputSlides(post.id)
                          .then(setPreviews)
                          .catch((e) => toast.error(apiErrorMessage(e, "Nothing built yet")))
                      }
                    >
                      Load them
                    </Chip>
                  </div>
                ) : previews.length === 0 ? (
                  <Empty icon={ImageIcon} title="Nothing built yet">
                    Build the post and the slides and videos appear here.
                  </Empty>
                ) : (
                  <>
                    <Tabs
                      className="mb-3"
                      value={String(previewAccount)}
                      onChange={(k) => setPreviewAccount(Number(k))}
                      items={previews.map((p, i) => ({ key: String(i), label: String(p.account_name) }))}
                    />
                    {current?.account_role !== "master" && (current?.slides_3x4?.length ?? 0) === 0 && (
                      <Hint tone="bad">
                        No TikTok slides are on disk for {String(current?.account_name)}. The build record is still
                        here, but the rendered files are not — build it again before posting.
                      </Hint>
                    )}
                    {current?.account_role !== "master" && (current?.slides_3x4?.length ?? 0) > 0 && (
                      <>
                        <div className="mb-2.5 text-[10.5px] font-bold uppercase leading-normal tracking-[0.08em] text-subtle">
                          TikTok slides 3:4
                          <em className="ml-2 text-[10.5px] font-semibold normal-case not-italic tracking-normal opacity-80">
                            click one to see it big, or its Text button to move the words
                          </em>
                        </div>
                        <div className="mb-4 flex flex-wrap gap-2">
                          {(current?.slides_3x4 ?? []).map((path, i) => (
                            <div
                              key={i}
                              className="flex h-[88px] w-[66px] flex-col overflow-hidden rounded-[10px] border border-border bg-card"
                            >
                              <button
                                type="button"
                                onClick={() =>
                                  onZoom({
                                    src: `${fileUrl(path)}?v=${cacheKey}`,
                                    caption: `Slide ${i + 1} · ${current?.account_name}`,
                                  })
                                }
                                aria-label={`See slide ${i + 1} full size`}
                                className="flex-1 overflow-hidden"
                              >
                                <SlideImage src={`${fileUrl(path)}?v=${cacheKey}`} label={i + 1} />
                              </button>
                              <button
                                type="button"
                                onClick={() =>
                                  setEditing({
                                    accountId: Number(current?.account_id),
                                    name: String(current?.account_name),
                                    index: i,
                                  })
                                }
                                className="flex items-center justify-center gap-1 border-t border-border bg-card py-1 text-[9.5px] font-semibold text-muted-foreground hover:bg-secondary"
                              >
                                <Type className="h-2.5 w-2.5" />
                                Text
                              </button>
                            </div>
                          ))}
                        </div>
                      </>
                    )}

                    <div className="mb-2.5 text-[10.5px] font-bold uppercase leading-normal tracking-[0.08em] text-subtle">
                      Video 9:16
                    </div>
                    <div className="mb-2.5 flex flex-wrap items-center gap-2.5">
                      <Tabs
                        value={platform}
                        onChange={(k) => setPlatform(k as VideoPlatform)}
                        items={VIDEO_PLATFORMS.map((p) => ({ key: p, label: PLAT_NAME[p] }))}
                      />
                      <Chip
                        icon={RefreshCw}
                        className="ml-auto"
                        onClick={() =>
                          regenerateVideo(post.id, Number(current?.account_id), platform)
                            .then(() => {
                              toast.success(`Rebuilding the ${PLAT_NAME[platform]} video`);
                              onChange();
                            })
                            .catch((e) => toast.error(apiErrorMessage(e, "Could not rebuild that")))
                        }
                      >
                        Rebuild {PLAT_NAME[platform]}
                      </Chip>
                    </div>
                    <VideoBox src={current?.[`${platform}_video_path`] as string | undefined} cacheKey={cacheKey} />
                    {current?.account_role === "master" && (
                      <Hint>No TikTok slides here — the master account skips TikTok.</Hint>
                    )}
                  </>
                )}

                <div className="mt-4 text-[10.5px] font-bold uppercase leading-normal tracking-[0.08em] text-subtle">
                  Files
                </div>
                <div className="mt-2 flex flex-col gap-2">
                  {(post.outputs ?? []).map((o) => {
                    const a = accounts.find((x) => x.id === o.account_id);
                    return (
                      <div key={o.id} className="flex items-center gap-2.5 rounded-[12px] border border-border bg-card px-3.5 py-2.5">
                        <span className="min-w-0 flex-1">
                          <span className="block text-[12.5px] font-semibold leading-normal">{a?.name ?? "Account"}</span>
                          <span className="block text-[11px] leading-normal text-subtle">
                            {String(o.posting_status ?? "ready")}
                          </span>
                        </span>
                        <Chip icon={Download} onClick={() => downloadFile(post.id, o.account_id).catch(() => toast.error("Nothing to download"))}>
                          ZIP
                        </Chip>
                      </div>
                    );
                  })}
                  {built && (
                    <Chip icon={Download} className="justify-center" onClick={() => downloadFile(post.id).catch(() => toast.error("Nothing to download"))}>
                      Download everything as one ZIP
                    </Chip>
                  )}
                </div>
              </CardBody>
            </Card>
          </div>
        }
        rail={
          <div className="flex flex-col gap-4">
            <Card>
              <CardHead
                title="Publish"
                sub={
                  post.scheduled_time
                    ? `Scheduled for ${DAY.format(new Date(`${post.date}T00:00:00`))} at ${post.scheduled_time.slice(0, 5)}`
                    : "Not scheduled yet"
                }
                right={
                  <DotsMenu
                    label="Publish options"
                    items={[{ icon: Clock, label: "Open the schedule", href: "/schedule" }]}
                  />
                }
              />
              <CardBody className="pt-3">
                <div className="grid grid-cols-2 gap-2.5">
                  <Field label="Date">
                    {/* The date is fixed when the post is built — the folder its
                        files live in is named after it. Moving a post to another
                        day is a duplicate, not an edit. */}
                    <Input value={post.date} readOnly title="A post belongs to the day it was built for" />
                  </Field>
                  <Field label="Time">
                    <Input type="time" value={time} onChange={(e) => setTime(e.target.value)} />
                  </Field>
                </div>
                {post.brand?.default_post_times && (
                  <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
                    <span className="mr-0.5 text-[11px] leading-normal text-subtle">{post.brand.name} usually posts at</span>
                    {post.brand.default_post_times.split(",").map((t) => (
                      <button
                        key={t}
                        type="button"
                        onClick={() => setTime(t.trim())}
                        className={`rounded-[8px] border px-2.5 py-1 text-[11.5px] font-semibold tabular-nums leading-normal transition-colors ${
                          time === t.trim()
                            ? "border-primary bg-primary text-primary-foreground"
                            : "border-border bg-card text-muted-foreground hover:bg-secondary"
                        }`}
                      >
                        {t.trim()}
                      </button>
                    ))}
                  </div>
                )}
                {post.brand?.timezone && <Hint>Times are {post.brand.timezone}, the brand&apos;s timezone.</Hint>}

                {(gated || reachable === 0) && (
                  <p className="mt-3.5 rounded-[11px] bg-[rgba(235,104,52,0.1)] px-3 py-2.5 text-[11.5px] leading-[1.5] text-[#B25E09] dark:text-[#F2A25C]">
                    <Info className="mr-1.5 inline h-3 w-3" />
                    {gated
                      ? "Save the TikTok setup above before this post can go out."
                      : "No platform is connected on any of these accounts, so there is nowhere for this to go. Connect one on Brands."}
                  </p>
                )}

                <div className="mt-2 flex flex-col gap-2">
                  <GhostButton onClick={saveTime} disabled={gated || savingTime || !time} className="w-full justify-center">
                    <Clock className="mr-1.5 inline h-3.5 w-3.5" />
                    {savingTime ? "Saving…" : "Save the schedule"}
                  </GhostButton>
                  <PrimaryButton
                    icon={Send}
                    onClick={onPostNow}
                    disabled={gated || !built || reachable === 0}
                    className="w-full justify-center"
                  >
                    Post it now
                  </PrimaryButton>
                </div>
                <Hint>Posting now sends it to every connected account immediately and takes it off the schedule.</Hint>
              </CardBody>
            </Card>

            <Card>
              <CardHead
                title="Music"
                sub="For the rendered videos"
                right={
                  <DotsMenu label="Music options" items={[{ icon: FileText, label: "Open the music library", href: "/music" }]} />
                }
              />
              <CardBody className="pt-2">
                {VIDEO_PLATFORMS.map((p) => {
                  const linked = accounts.some((a) => a[`${p}_token`]);
                  const usable = tracks.filter((t) => (t.platforms_allowed || "").includes(p));
                  return (
                    <div key={p} className={`flex items-center gap-2.5 border-b border-line-2 py-2.5 last:border-b-0 ${linked ? "" : "opacity-55"}`}>
                      <span className="grid h-7 w-7 flex-none place-items-center rounded-[9px] border border-border bg-secondary text-muted-foreground">
                        <PlatformIcon platform={p} className="h-3.5 w-3.5" />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-[12.5px] font-semibold leading-normal">{PLAT_NAME[p]}</span>
                        {!linked && <span className="block text-[11px] leading-normal text-subtle">No account connected</span>}
                      </span>
                      <select
                        value={music[p] ?? 0}
                        disabled={!linked}
                        onChange={(e) => saveMusic(p, Number(e.target.value) || null)}
                        aria-label={`${PLAT_NAME[p]} track`}
                        className="max-w-[140px] flex-none rounded-[9px] border border-border bg-card px-2 py-1 text-[11.5px] outline-none disabled:opacity-50"
                      >
                        <option value={0}>No music</option>
                        {usable.map((t) => (
                          <option key={t.id} value={t.id}>
                            {t.name}
                          </option>
                        ))}
                      </select>
                    </div>
                  );
                })}
                <Hint>
                  TikTok is not in this list. It gets a swipeable photo post, and the sound is picked from TikTok&apos;s
                  own library when it publishes.
                </Hint>
                <div className="mt-2.5">
                  <Chip href="/music" icon={ArrowRight} className="w-full justify-center">
                    Music library
                  </Chip>
                </div>
              </CardBody>
            </Card>
          </div>
        }
      />

      {editing && (
        <SlideTextDialog
          open
          postId={post.id}
          accountId={editing.accountId}
          accountName={editing.name}
          slides={slidesFor}
          startAt={editing.index}
          onClose={() => setEditing(null)}
          onDone={onChange}
        />
      )}

    </>
  );
}

function Stat({ n, label, note }: { n: number; label: string; note?: string }) {
  return (
    <div className="rounded-[12px] border border-border bg-secondary px-3.5 py-3">
      <span className="block text-xl font-extrabold leading-none tabular-nums tracking-[-0.03em]">{n}</span>
      <span className="mt-0.5 block text-[11px] font-semibold leading-normal text-muted-foreground">{label}</span>
      {note && <span className="mt-0.5 block text-[10px] leading-normal text-subtle">{note}</span>}
    </div>
  );
}

function VideoBox({ src, cacheKey }: { src?: string; cacheKey: number }) {
  if (!src)
    return (
      <div className="grid h-[196px] place-items-center rounded-[13px] border border-border bg-secondary text-[11.5px] text-subtle">
        Not built for this platform yet
      </div>
    );
  return (
    <video controls className="w-full max-w-[260px] rounded-[13px] border border-border" src={`${fileUrl(src)}?v=${cacheKey}`} />
  );
}

function PostNowFlow({
  post,
  accounts,
  master,
  onClose,
}: {
  post: Post;
  accounts: Account[];
  master?: Account;
  onClose: () => void;
}) {
  const [phase, setPhase] = useState<"confirm" | "sending">("confirm");
  const [results, setResults] = useState<PostResult[] | null>(null);

  // The master leads here too, as it does on the variations strip.
  const destinations = [...accounts]
    .sort((x, y) => Number(y.role === "master") - Number(x.role === "master"))
    .map((a) => ({
      account: a.name,
      platforms: (["tiktok", "instagram", "youtube", "facebook"] as const).filter(
        (p) => a[`${p}_token`] && !(a.role === "master" && p === "tiktok"),
      ) as string[],
    }));
  const total = destinations.reduce((n, d) => n + d.platforms.length, 0);

  const going = destinations.filter((d) => d.platforms.length);

  // Posting is irreversible, but it is not a deletion — the destructive
  // confirm's red trash tile and danger button would say the wrong thing
  // about an action whose whole point is to publish. It gets its own.
  if (phase === "confirm")
    return (
      <Dialog open onClose={onClose} label="Post it now" size="confirm">
        <DialogHead
          title="Post it now?"
          sub={`It goes out immediately on ${spell(going.length)} account${going.length === 1 ? "" : "s"}. Nothing here can pull it back — you would have to delete it on each platform.`}
          onClose={onClose}
          icon={
            <span className="grid h-[34px] w-[34px] flex-none place-items-center rounded-[11px] border border-border bg-secondary text-foreground">
              <Send className="h-4 w-4" />
            </span>
          }
        />
        <DialogBody>
          <div className="flex flex-col gap-2">
            {going.map((d) => (
              <div
                key={d.account}
                className="flex items-center gap-2.5 rounded-[12px] border border-border bg-card px-3 py-2.5"
              >
                <span className="grid h-[29px] w-[29px] flex-none place-items-center rounded-[9px] border border-border bg-secondary text-muted-foreground">
                  <PlatformIcon platform={d.platforms[0]} className="h-3.5 w-3.5" />
                </span>
                <span className="min-w-0">
                  <span className="block text-[13px] font-semibold leading-normal">{d.account}</span>
                  <span className="block text-[11px] leading-normal text-subtle">
                    {listOf(d.platforms.map((pl) => PLAT_NAME[pl]))}
                    {d.account === master?.name ? " — the master skips TikTok" : ""}
                  </span>
                </span>
              </div>
            ))}
          </div>
          {post.scheduled_time && (
            <Hint>
              Its {post.scheduled_time.slice(0, 5)} schedule is dropped — the scheduler will not send it a second time.
            </Hint>
          )}
        </DialogBody>
        <DialogFoot>
          <GhostButton onClick={onClose}>Cancel</GhostButton>
          <PrimaryButton
            icon={Send}
            onClick={async () => {
              setPhase("sending");
              try {
                const res = await postNow(post.id);
                setResults(res.results || []);
              } catch (e) {
                toast.error(apiErrorMessage(e, "Post Now failed"));
                onClose();
              }
            }}
          >
            Post to {total} {total === 1 ? "place" : "places"}
          </PrimaryButton>
        </DialogFoot>
      </Dialog>
    );

  return (
    <PostingModal
      open
      destinations={going}
      results={results}
      onResults={setResults}
      onClose={onClose}
    />
  );
}
