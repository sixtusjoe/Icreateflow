"use client";

/** The music library.
 *
 *  A track here is backing audio for the rendered 9:16 videos — YouTube,
 *  Instagram and Facebook. TikTok is deliberately absent: a brand post
 *  reaches TikTok as a swipeable photo set and takes its sound from
 *  TikTok's own library, so nothing here ever gets there. The page says so
 *  rather than leaving it to be discovered.
 *
 *  `platforms_allowed` is the only real state a track carries, and it is
 *  not a preference — it is the operator's note on whether they hold a
 *  commercial licence for that platform. Nothing checks it; it decides
 *  which tracks a post is offered. The old page drew it as three unlabelled
 *  toggles in a box.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { Music2, Upload, Pause, Play, Search, Trash2, Pencil, Download, Info, FileText, Shield } from "lucide-react";
import {
  getMusicTracks,
  getPosts,
  uploadMusicTrack,
  updateMusicTrack,
  deleteMusicTrack,
  fileUrl,
} from "@/lib/api";
import {
  Card,
  CardBody,
  CardHead,
  Chip,
  ChipCount,
  DotsMenu,
  Empty,
  FigureLine,
  FigureStrong,
  Minis,
  Note,
  PageActions,
  PageHead,
  PageTitle,
  PlatformIcon,
  PrimaryButton,
  Skeleton,
  Tabs,
  TwoCol,
  n,
} from "@/components/kit";
import {
  Checkbox,
  ConfirmDialog,
  Dialog,
  DialogBody,
  DialogFoot,
  DialogHead,
  Field,
  GhostButton,
  Hint,
  Input,
} from "@/components/kit/dialog";
import { apiErrorMessage } from "@/components/kit/format";

type Track = {
  id: number;
  name: string;
  genre?: string | null;
  duration?: number | null;
  is_custom?: boolean;
  platforms_allowed?: string | null;
  file_path: string;
};

/** The three the renderer can lay under a video. TikTok is not one of them. */
const PLATS = ["youtube", "instagram", "facebook"] as const;
type Plat = (typeof PLATS)[number];

const allowedSet = (t: Track) =>
  new Set(
    (t.platforms_allowed || "")
      .split(",")
      .map((s) => s.trim().toLowerCase())
      .filter(Boolean),
  );

const mmss = (sec: number) => `${Math.floor(sec / 60)}:${String(Math.round(sec % 60)).padStart(2, "0")}`;

/** A deterministic little waveform, so a track looks like a track. The real
 *  peaks would need decoding the file; this only has to read as audio. */
const noise = (a: number) => {
  const t = Math.sin(a * 12.9898) * 43758.5453;
  return t - Math.floor(t);
};

function Wave({ seed, playing }: { seed: number; playing: boolean }) {
  const bars = useMemo(
    () => Array.from({ length: 44 }, (_, i) => 18 + Math.floor(noise(seed * 97 + i * 13 + 7) * 62)),
    [seed],
  );
  return (
    <div className="hidden h-[30px] w-[248px] flex-none items-center gap-[2px] xl:flex" aria-hidden>
      {bars.map((pct, i) => (
        <i
          key={i}
          className={`flex-1 rounded-full ${playing ? "bg-chart-1" : "bg-line-2"}`}
          style={{ height: `${pct}%`, minHeight: 2 }}
        />
      ))}
    </div>
  );
}

export default function MusicPage() {
  const [tracks, setTracks] = useState<Track[] | null>(null);
  const [usage, setUsage] = useState<Record<number, number>>({});
  const [postCount, setPostCount] = useState(0);
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [toDelete, setToDelete] = useState<Track | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [playing, setPlaying] = useState<number | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);

  const load = useCallback(async () => {
    try {
      setTracks(await getMusicTracks());
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not load the library"));
      setTracks([]);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // How many posts point at each track. There is no endpoint for it, so it is
  // counted off the posts themselves — a post carries one track per platform.
  useEffect(() => {
    getPosts()
      .then((posts: Record<string, number | null>[]) => {
        const counts: Record<number, number> = {};
        for (const p of posts) {
          const ids = new Set(
            (["music_track_id", "youtube_music_track_id", "instagram_music_track_id", "facebook_music_track_id"] as const)
              .map((k) => p[k])
              .filter((v): v is number => typeof v === "number"),
          );
          ids.forEach((id) => (counts[id] = (counts[id] ?? 0) + 1));
        }
        setUsage(counts);
        setPostCount(posts.length);
      })
      .catch(() => {
        /* the count is a nicety; the library still works without it */
      });
  }, []);

  // One track plays at a time, and leaving the page stops it.
  const toggle = (t: Track) => {
    if (playing === t.id) {
      audio.current?.pause();
      setPlaying(null);
      return;
    }
    audio.current?.pause();
    const el = new Audio(fileUrl(t.file_path));
    el.onended = () => setPlaying(null);
    el.onerror = () => {
      toast.error(`Could not play ${t.name}`);
      setPlaying(null);
    };
    audio.current = el;
    el.play().catch(() => {
      toast.error(`Could not play ${t.name}`);
      setPlaying(null);
    });
    setPlaying(t.id);
  };
  useEffect(() => () => audio.current?.pause(), []);

  const toggleClearance = async (t: Track, plat: Plat) => {
    const next = allowedSet(t);
    if (next.has(plat)) next.delete(plat);
    else next.add(plat);
    const csv = [...next].sort().join(",");
    // Optimistic: the toggle is the whole interaction, so it must not wait.
    setTracks((prev) => prev?.map((x) => (x.id === t.id ? { ...x, platforms_allowed: csv } : x)) ?? prev);
    try {
      await updateMusicTrack(t.id, { platforms_allowed: csv });
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not save that"));
      load();
    }
  };

  const remove = async () => {
    if (!toDelete) return;
    setDeleting(true);
    try {
      await deleteMusicTrack(toDelete.id);
      toast.success(`${toDelete.name} deleted`);
      setToDelete(null);
      load();
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not delete that track"));
    } finally {
      setDeleting(false);
    }
  };

  const list = useMemo(() => tracks ?? [], [tracks]);
  const per = useMemo(
    () => Object.fromEntries(PLATS.map((p) => [p, list.filter((t) => allowedSet(t).has(p)).length])) as Record<Plat, number>,
    [list],
  );
  const unused = list.filter((t) => !usage[t.id]).length;
  const totalSecs = list.reduce((a, t) => a + (t.duration ?? 0), 0);

  const shown = list.filter((t) => {
    if (query && !t.name.toLowerCase().includes(query.toLowerCase())) return false;
    if (filter === "unused") return !usage[t.id];
    if (filter === "all") return true;
    return allowedSet(t).has(filter);
  });

  const gaps = list.filter((t) => allowedSet(t).size < PLATS.length);

  return (
    <>
      <PageHead>
        <PageTitle title="Music" sub="Backing tracks for the rendered videos. Nothing here reaches TikTok." />
        <PageActions>
          <Chip href="/posts" icon={FileText}>
            Posts
            <ChipCount>{postCount}</ChipCount>
          </Chip>
          <PrimaryButton icon={Upload} onClick={() => setUploadOpen(true)}>
            Upload a track
          </PrimaryButton>
        </PageActions>
      </PageHead>

      {tracks === null ? (
        <div className="flex flex-col gap-4">
          <Skeleton className="h-[220px]" />
          <Skeleton className="h-[260px]" />
        </div>
      ) : list.length === 0 ? (
        <Card>
          <EmptyLibrary onUpload={() => setUploadOpen(true)} />
        </Card>
      ) : (
        <div className="flex flex-col gap-4">
          <TwoCol
            main={
              <Card>
                <CardHead
                  title="Your library"
                  sub="Everything a post can pick from"
                  right={
                    <DotsMenu
                      label="Library options"
                      items={[{ icon: Upload, label: "Upload a track", onClick: () => setUploadOpen(true) }]}
                    />
                  }
                />
                <CardBody>
                  <FigureLine value={n(list.length)}>
                    tracks
                    {totalSecs > 0 && (
                      <>
                        {" · "}
                        <FigureStrong>{mmss(totalSecs)}</FigureStrong> of music between them
                      </>
                    )}
                  </FigureLine>
                  <Minis
                    cells={[
                      { label: "YOUTUBE", value: per.youtube },
                      { label: "INSTAGRAM", value: per.instagram },
                      { label: "FACEBOOK", value: per.facebook },
                      { label: "TIKTOK", value: 0 },
                    ]}
                  />
                  <p className="relative mt-4 pl-[19px] text-[11px] leading-[1.5] text-subtle">
                    <Info className="absolute left-0 top-[2px] h-3 w-3" />
                    TikTok is zero and always will be — a brand post gets a photo set there, and the sound is chosen
                    inside TikTok.
                  </p>
                </CardBody>
              </Card>
            }
            rail={
              <Card>
                <CardHead title="Not cleared everywhere" sub="These will not be offered on some platforms" />
                <CardBody className="pt-3">
                  {gaps.length === 0 ? (
                    <p className="text-[12.5px] leading-[1.5] text-subtle">
                      Every track is marked as cleared for all three.
                    </p>
                  ) : (
                    <div className="flex flex-col gap-[9px]">
                      {gaps.slice(0, 5).map((t) => {
                        const missing = PLATS.filter((p) => !allowedSet(t).has(p));
                        return (
                          <div key={t.id} className="flex items-center gap-2.5">
                            <span className="min-w-0 flex-1 truncate text-[12.5px] font-semibold leading-normal text-foreground">
                              {t.name}
                            </span>
                            <span className="flex flex-none items-center gap-1.5 text-[11px] leading-normal text-subtle">
                              {missing.map((p) => (
                                <PlatformIcon key={p} platform={p} className="h-[13px] w-[13px]" />
                              ))}
                              {missing.length === 1 ? `not cleared for ${missing[0] === "youtube" ? "YouTube" : missing[0] === "instagram" ? "Instagram" : "Facebook"}` : `${missing.length} platforms`}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  )}
                  <Hint>
                    Clearance is your note, not a check we run. Nothing stops you ticking a platform you do not have the
                    rights for.
                  </Hint>
                </CardBody>
              </Card>
            }
          />

          <div className="flex flex-wrap items-center gap-2">
            <Tabs
              value={filter}
              onChange={setFilter}
              items={[
                { key: "all", label: "All", count: list.length },
                { key: "youtube", label: "YouTube", count: per.youtube },
                { key: "instagram", label: "Instagram", count: per.instagram },
                { key: "facebook", label: "Facebook", count: per.facebook },
                { key: "unused", label: "Unused", count: unused },
              ]}
            />
            <label className="ml-auto flex items-center gap-2 rounded-[11px] border border-border bg-card px-3 py-2 shadow-card">
              <Search className="h-[13px] w-[13px] text-subtle" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search tracks"
                aria-label="Search tracks"
                className="w-[140px] bg-transparent text-[12.5px] leading-normal outline-none placeholder:text-subtle"
              />
            </label>
          </div>

          <Card>
            {shown.length === 0 ? (
              <Empty icon={Music2} title="Nothing matches that">
                {filter === "unused"
                  ? "Every track is used by at least one post."
                  : "Tick a platform on a track to make it pickable there."}
              </Empty>
            ) : (
              <div className="py-1.5">
                {shown.map((t, i) => (
                  <TrackRow
                    key={t.id}
                    track={t}
                    index={i}
                    used={usage[t.id] ?? 0}
                    playing={playing === t.id}
                    onPlay={() => toggle(t)}
                    onClearance={(p) => toggleClearance(t, p)}
                    onDelete={() => setToDelete(t)}
                  />
                ))}
              </div>
            )}
          </Card>

          <Note>
            A post picks its track per platform, so the same post can carry one piece of music on YouTube and another on
            Instagram.
          </Note>
        </div>
      )}

      <UploadDialog open={uploadOpen} onClose={() => setUploadOpen(false)} onDone={load} />

      <ConfirmDialog
        open={!!toDelete}
        onClose={() => setToDelete(null)}
        onConfirm={remove}
        busy={deleting}
        title="Delete this track?"
        body={`The audio file goes with it. This cannot be undone.`}
        bullets={[
          `${toDelete?.name ?? "The track"} and its clearance notes`,
          ...(toDelete && usage[toDelete.id]
            ? [
                `${usage[toDelete.id]} post${usage[toDelete.id] > 1 ? "s are" : " is"} set to use it — they keep the videos already built, but building again will leave those platforms silent`,
              ]
            : []),
        ]}
        confirmLabel="Delete track"
      />
    </>
  );
}

function EmptyLibrary({ onUpload }: { onUpload: () => void }) {
  const facts = [
    {
      icon: FileText,
      title: "MP3 or WAV",
      body: "Anything shorter than the video loops to fill it",
    },
    {
      icon: Shield,
      title: "Cleared per platform",
      body: "You mark which platforms a track is licensed for, and a post only offers it there",
    },
    {
      icon: null,
      title: "TikTok never uses these",
      body: "A brand post reaches TikTok as a photo set and takes its sound from TikTok's own library",
    },
  ];
  return (
    <div className="flex flex-col items-center px-7 pb-10 pt-[46px] text-center">
      <span className="grid h-[52px] w-[52px] place-items-center rounded-[16px] border border-border bg-secondary">
        <Music2 className="h-6 w-6 text-subtle" strokeWidth={1.6} />
      </span>
      <h2 className="mt-4 text-[17px] font-extrabold leading-normal tracking-[-0.02em]">Nothing in the library yet</h2>
      <p className="mx-auto mt-2 max-w-[52ch] text-[12.5px] leading-[1.6] text-subtle">
        A track here is laid under the 9:16 videos when a post is built — the YouTube, Instagram and Facebook ones.
        Upload the music you have the rights to and it becomes pickable on every post you make.
      </p>
      <div className="mt-5">
        <PrimaryButton icon={Upload} onClick={onUpload}>
          Upload a track
        </PrimaryButton>
      </div>
      <div className="mt-8 grid w-full max-w-[760px] grid-cols-1 gap-2.5 text-left lg:grid-cols-3">
        {facts.map((f) => {
          const Icon = f.icon;
          return (
            <div key={f.title} className="flex gap-2.5 rounded-[13px] border border-border bg-secondary px-3.5 py-3">
              <span className="mt-px flex-none text-subtle">
                {Icon ? <Icon className="h-[15px] w-[15px]" /> : <PlatformIcon platform="tiktok" className="h-[15px] w-[15px]" />}
              </span>
              <span className="min-w-0">
                <span className="block text-[12.5px] font-semibold leading-normal text-foreground">{f.title}</span>
                <span className="mt-0.5 block text-[11px] leading-[1.5] text-subtle">{f.body}</span>
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function TrackRow({
  track,
  index,
  used,
  playing,
  onPlay,
  onClearance,
  onDelete,
}: {
  track: Track;
  index: number;
  used: number;
  playing: boolean;
  onPlay: () => void;
  onClearance: (p: Plat) => void;
  onDelete: () => void;
}) {
  const allowed = allowedSet(track);
  return (
    <div className="flex flex-wrap items-center gap-3.5 border-b border-line-2 px-[18px] py-3 last:border-b-0 hover:bg-secondary">
      <button
        type="button"
        onClick={onPlay}
        aria-label={`${playing ? "Pause" : "Play"} ${track.name}`}
        className="grid h-[34px] w-[34px] flex-none place-items-center rounded-full border border-border bg-card text-foreground transition-colors hover:border-primary hover:bg-primary hover:text-primary-foreground"
      >
        {playing ? <Pause className="h-[13px] w-[13px] fill-current" /> : <Play className="ml-0.5 h-[13px] w-[13px] fill-current" />}
      </button>

      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-[7px]">
          <span className="truncate text-[13px] font-semibold leading-normal">{track.name}</span>
          {track.genre && (
            <span className="flex-none rounded-full border border-border bg-secondary px-[7px] py-px text-[10px] font-semibold leading-normal text-subtle">
              {track.genre}
            </span>
          )}
          {track.is_custom && (
            <span className="flex-none rounded-full border border-primary bg-primary px-[7px] py-px text-[10px] font-semibold leading-normal text-primary-foreground">
              yours
            </span>
          )}
        </div>
        <div className="mt-0.5 text-[11px] leading-normal tabular-nums text-subtle">
          {track.duration ? `${mmss(track.duration)} · ` : ""}
          {used === 0 ? "Not used by any post" : `Used by ${used} post${used > 1 ? "s" : ""}`}
        </div>
      </div>

      <Wave seed={index} playing={playing} />

      <div className="flex flex-none items-center gap-[2px] rounded-[10px] border border-border bg-secondary p-[2px]">
        {PLATS.map((p) => {
          const on = allowed.has(p);
          const label = p === "youtube" ? "YouTube" : p === "instagram" ? "Instagram" : "Facebook";
          return (
            <button
              key={p}
              type="button"
              onClick={() => onClearance(p)}
              aria-pressed={on}
              title={`${track.name}: ${on ? "cleared" : "not cleared"} for ${label}`}
              className={`flex items-center gap-1.5 whitespace-nowrap rounded-[8px] px-[9px] py-[5px] text-[11px] font-semibold leading-normal transition-colors ${
                on ? "bg-card text-foreground shadow-card" : "text-subtle hover:text-foreground"
              }`}
            >
              <PlatformIcon platform={p} className={`h-3 w-3 ${on ? "" : "opacity-75"}`} />
              {label}
            </button>
          );
        })}
      </div>

      <DotsMenu
        label={`${track.name} actions`}
        items={[
          { icon: Pencil, label: "Rename", onClick: () => toast.message("Renaming is not wired yet") },
          { icon: Download, label: "Download", href: fileUrl(track.file_path) },
          "-",
          { icon: Trash2, label: "Delete track", danger: true, onClick: onDelete },
        ]}
      />
    </div>
  );
}

function UploadDialog({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [genre, setGenre] = useState("");
  const [cleared, setCleared] = useState<Record<Plat, boolean>>({ youtube: true, instagram: true, facebook: true });
  const [busy, setBusy] = useState(false);
  const picker = useRef<HTMLInputElement | null>(null);

  const reset = () => {
    setFile(null);
    setName("");
    setGenre("");
    setCleared({ youtube: true, instagram: true, facebook: true });
  };

  const pick = (f: File | null) => {
    if (!f) return;
    setFile(f);
    // A sensible first guess at the name, which the operator can overwrite.
    if (!name) setName(f.name.replace(/\.[^.]+$/, "").replace(/[-_]+/g, " ").trim());
  };

  const submit = async () => {
    if (!file || !name.trim()) return;
    setBusy(true);
    try {
      const track = await uploadMusicTrack(name.trim(), genre.trim(), file);
      // The server clears a new track for all three. Only correct it when the
      // operator asked for something narrower.
      const want = PLATS.filter((p) => cleared[p]);
      if (want.length !== PLATS.length) {
        await updateMusicTrack(track.id, { platforms_allowed: want.join(",") });
      }
      toast.success(`${name.trim()} uploaded`);
      reset();
      onClose();
      onDone();
    } catch (e) {
      toast.error(apiErrorMessage(e, "Upload failed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} label="Upload a track" size="md">
      <DialogHead title="Upload a track" sub="It becomes pickable on every post, per platform." onClose={onClose} />
      <DialogBody>
        <input
          ref={picker}
          type="file"
          accept="audio/*"
          className="hidden"
          onChange={(e) => pick(e.target.files?.[0] ?? null)}
        />
        {!file ? (
          <button
            type="button"
            onClick={() => picker.current?.click()}
            className="flex w-full flex-col items-center gap-1.5 rounded-[14px] border border-dashed border-border bg-secondary px-5 py-[26px] transition-colors hover:border-subtle hover:bg-card"
          >
            <span className="grid h-[38px] w-[38px] place-items-center rounded-[11px] border border-border bg-card">
              <Upload className="h-[17px] w-[17px] text-subtle" strokeWidth={1.8} />
            </span>
            <span className="text-[13px] font-semibold leading-normal">
              Choose an audio file, or <b className="underline">browse</b>
            </span>
            <span className="text-[11px] leading-normal text-subtle">MP3 or WAV</span>
          </button>
        ) : (
          <div className="flex items-center gap-2.5 rounded-[13px] border border-border bg-card px-3.5 py-3">
            <span className="grid h-[30px] w-[30px] flex-none place-items-center rounded-full border border-border bg-secondary">
              <Music2 className="h-[13px] w-[13px] text-subtle" />
            </span>
            <div className="min-w-0 flex-1">
              <div className="truncate text-[12.5px] font-semibold leading-normal">{file.name}</div>
              <div className="text-[11px] leading-normal text-subtle">{(file.size / 1_048_576).toFixed(1)} MB</div>
            </div>
            <GhostButton onClick={() => setFile(null)}>Pick another</GhostButton>
          </div>
        )}

        <div className="mt-3.5 grid grid-cols-1 gap-2.5 sm:grid-cols-2">
          <Field label="Name it">
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Slow Aisle" />
          </Field>
          <Field label="Genre">
            <Input value={genre} onChange={(e) => setGenre(e.target.value)} placeholder="lo-fi, upbeat, cinematic…" />
          </Field>
        </div>

        <div className="mt-4">
          <div className="mb-2 text-[10.5px] font-bold uppercase leading-normal tracking-[0.09em] text-subtle">
            Cleared for
          </div>
          <div className="flex flex-col gap-0.5">
            {PLATS.map((p) => (
              <Checkbox key={p} checked={cleared[p]} onChange={(v) => setCleared((c) => ({ ...c, [p]: v }))}>
                <span className="flex items-center gap-2">
                  <PlatformIcon platform={p} className="h-[13px] w-[13px] text-subtle" />
                  {p === "youtube" ? "YouTube" : p === "instagram" ? "Instagram" : "Facebook"}
                </span>
              </Checkbox>
            ))}
          </div>
          <Hint>
            This is your own note about the licence you hold. We do not check it — a post simply will not offer the track
            on a platform you have not ticked.
          </Hint>
        </div>
      </DialogBody>
      <DialogFoot>
        <GhostButton onClick={onClose}>Cancel</GhostButton>
        <PrimaryButton icon={Upload} onClick={submit} disabled={!file || !name.trim() || busy}>
          {busy ? "Uploading…" : "Upload"}
        </PrimaryButton>
      </DialogFoot>
    </Dialog>
  );
}
