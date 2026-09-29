"use client";

/** Brands.
 *
 *  A brand is the look a post is built in — its colour, its timezone, when
 *  it posts — plus the accounts that carry it. One account is the master: it
 *  posts the slides as imported, and every other account gets its own copy
 *  of each slide so the same images do not go out twice.
 *
 *  An account carries four handles, and a handle is only a name. Posting to
 *  it also needs the platform connected, which is a separate sign-in and
 *  lives behind the account's "..." rather than on the card, so the card
 *  stays a list of accounts rather than a wall of connect buttons.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import {
  Copy,
  Download,
  FileText,
  Plus,
  Tag as TagIcon,
  Trash2,
  X,
} from "lucide-react";
import {
  createAccount,
  createBrand,
  deleteAccount,
  deleteBrand,
  getBrands,
  getPosts,
  updateAccount,
  updateBrand,
} from "@/lib/api";
import OAuthTiles from "@/components/OAuthTiles";
import {
  Card,
  CardHead,
  Chip,
  ChipCount,
  CollapseButton,
  DotsMenu,
  Empty,
  Note,
  PageActions,
  PageHead,
  PageTitle,
  PlatformIcon,
  PrimaryButton,
  Skeleton,
  Tag,
  useCollapsed,
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
} from "@/components/kit/dialog";
import { apiErrorMessage } from "@/components/kit/format";

const PLATS = ["tiktok", "instagram", "youtube", "facebook"] as const;
type Plat = (typeof PLATS)[number];
const PLAT_NAME: Record<Plat, string> = {
  tiktok: "TikTok",
  instagram: "Instagram",
  youtube: "YouTube",
  facebook: "Facebook",
};

type Account = Record<string, unknown> & { id: number; brand_id: number; name: string; role: string };
type Brand = {
  id: number;
  name: string;
  slug: string;
  background_color?: string;
  timezone?: string;
  default_post_times?: string;
  accounts?: Account[];
};

const handleOf = (a: Account, p: Plat) => (a[`${p}_handle`] as string | null) || null;
const connected = (a: Account, p: Plat) => !!a[`${p}_token`];

export default function BrandsPage() {
  const [brands, setBrands] = useState<Brand[] | null>(null);
  const [postCounts, setPostCounts] = useState<Record<number, number>>({});
  const [shut, toggle] = useCollapsed("brands_collapsed");
  const [brandDialog, setBrandDialog] = useState<{ brand?: Brand } | null>(null);
  const [accountDialog, setAccountDialog] = useState<{ brand: Brand; account?: Account } | null>(null);
  const [connectFor, setConnectFor] = useState<Account | null>(null);
  const [toDeleteBrand, setToDeleteBrand] = useState<Brand | null>(null);
  const [toDeleteAccount, setToDeleteAccount] = useState<{ brand: Brand; account: Account } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setBrands(await getBrands());
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not load your brands"));
      setBrands([]);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    getPosts()
      .then((posts: { brand_id: number }[]) => {
        const c: Record<number, number> = {};
        posts.forEach((p) => (c[p.brand_id] = (c[p.brand_id] ?? 0) + 1));
        setPostCounts(c);
      })
      .catch(() => {});
  }, []);

  const list = useMemo(() => brands ?? [], [brands]);

  const act = async (fn: () => Promise<unknown>, done: string, fail: string, after?: () => void) => {
    setBusy(true);
    try {
      await fn();
      toast.success(done);
      after?.();
      load();
    } catch (e) {
      toast.error(apiErrorMessage(e, fail));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHead>
        <PageTitle title="Brands" sub="A brand is the look a post is built in, and the accounts that carry it." />
        <PageActions>
          <Chip href="/posts" icon={FileText}>
            Posts
            <ChipCount>{Object.values(postCounts).reduce((a, b) => a + b, 0)}</ChipCount>
          </Chip>
          <PrimaryButton icon={Plus} onClick={() => setBrandDialog({})}>
            New brand
          </PrimaryButton>
        </PageActions>
      </PageHead>

      {brands === null ? (
        <Skeleton className="h-[300px]" />
      ) : list.length === 0 ? (
        <Card>
          <Empty
            icon={TagIcon}
            title="No brands yet"
            action={
              <PrimaryButton icon={Plus} onClick={() => setBrandDialog({})}>
                Create your first brand
              </PrimaryButton>
            }
          >
            A brand holds the colour and the posting times a post is built with, and the accounts it goes out on.
          </Empty>
        </Card>
      ) : (
        <div className="flex flex-col gap-4">
          {list.map((b) => {
            const open = !shut[String(b.id)];
            // The master leads — it is the one the others are varied from.
            const accounts = [...(b.accounts ?? [])].sort(
              (x, y) => Number(y.role === "master") - Number(x.role === "master"),
            );
            const master = accounts.find((a) => a.role === "master");
            return (
              <Card key={b.id}>
                <CardHead
                  flush={false}
                  collapsed={!open}
                  title={
                    <span className="flex items-center gap-3">
                      <span
                        className="grid h-10 w-10 flex-none place-items-center rounded-[12px] border border-border text-base font-extrabold text-[#0b0d12]"
                        style={{ background: b.background_color || "#d4fb78" }}
                        aria-hidden
                      >
                        {b.name.charAt(0).toUpperCase()}
                      </span>
                      <span className="min-w-0">
                        <span className="block text-[14.5px] font-bold leading-normal">{b.name}</span>
                        <span className="block text-[11.5px] font-normal leading-normal text-subtle">
                          {b.slug} · {postCounts[b.id] ?? 0} posts · {accounts.length} accounts
                        </span>
                      </span>
                    </span>
                  }
                  right={
                    <>
                      <Chip icon={FileText} onClick={() => setBrandDialog({ brand: b })}>
                        Edit brand
                      </Chip>
                      <CollapseButton open={open} onToggle={() => toggle(String(b.id))} label={`Collapse ${b.name}`} />
                      <DotsMenu
                        label="Brand options"
                        items={[
                          { icon: Plus, label: "Add an account", onClick: () => setAccountDialog({ brand: b }) },
                          { icon: Download, label: "Export its posts", href: "/posts" },
                          "-",
                          { icon: Trash2, label: "Delete brand", danger: true, onClick: () => setToDeleteBrand(b) },
                        ]}
                      />
                    </>
                  }
                />

                {open && (
                  <>
                    <div className="grid grid-cols-2 gap-2.5 px-5 pb-4 lg:grid-cols-4">
                      <Meta label="Colour">
                        <i
                          className="h-[13px] w-[13px] flex-none rounded-[4px] border border-border"
                          style={{ background: b.background_color || "#000" }}
                        />
                        {b.background_color || "—"}
                      </Meta>
                      <Meta label="Timezone">{b.timezone || "—"}</Meta>
                      <Meta label="Posts at" wide>
                        {(b.default_post_times || "")
                          .split(",")
                          .map((t) => t.trim())
                          .filter(Boolean)
                          .map((t) => (
                            <span
                              key={t}
                              className="rounded-full border border-border bg-card px-2 py-0.5 text-[11.5px] font-semibold tabular-nums leading-normal"
                            >
                              {t}
                            </span>
                          ))}
                      </Meta>
                    </div>

                    <div className="border-t border-line-2 px-5 pb-5 pt-4">
                      <div className="mb-3 flex items-center gap-2.5">
                        <span className="text-[10.5px] font-bold uppercase leading-normal tracking-[0.08em] text-subtle">
                          Accounts
                        </span>
                        <em className="text-[10.5px] font-bold not-italic leading-normal tabular-nums text-subtle opacity-60">
                          {accounts.length}
                        </em>
                        <Chip icon={Plus} className="ml-auto" onClick={() => setAccountDialog({ brand: b })}>
                          Add account
                        </Chip>
                      </div>

                      {accounts.length === 0 ? (
                        <p className="rounded-[13px] border border-dashed border-border bg-secondary px-3.5 py-4 text-center text-[12px] leading-normal text-subtle">
                          This brand has no accounts, so nothing it builds can go anywhere.
                        </p>
                      ) : (
                        accounts.map((a) => (
                          <AccountRow
                            key={a.id}
                            account={a}
                            onEdit={() => setAccountDialog({ brand: b, account: a })}
                            onConnect={() => setConnectFor(a)}
                            onDelete={() => setToDeleteAccount({ brand: b, account: a })}
                            onMakeMaster={() =>
                              act(
                                async () => {
                                  if (master && master.id !== a.id) await updateAccount(master.id, { role: "variation" });
                                  await updateAccount(a.id, { role: "master" });
                                },
                                `${a.name} is now the master`,
                                "Could not change the master",
                              )
                            }
                          />
                        ))
                      )}
                    </div>
                  </>
                )}
              </Card>
            );
          })}

          <Note>
            One account per brand is the master. Every other account gets its own copy of each slide, because posting
            identical images from two accounts is the pattern a platform looks for.
          </Note>
        </div>
      )}

      {brandDialog && (
        <BrandDialog
          brand={brandDialog.brand}
          onClose={() => setBrandDialog(null)}
          onSaved={() => {
            setBrandDialog(null);
            load();
          }}
        />
      )}

      {accountDialog && (
        <AccountDialog
          brand={accountDialog.brand}
          account={accountDialog.account}
          master={(accountDialog.brand.accounts ?? []).find((a) => a.role === "master")}
          onClose={() => setAccountDialog(null)}
          onSaved={() => {
            setAccountDialog(null);
            load();
          }}
        />
      )}

      {connectFor && (
        <Dialog open onClose={() => setConnectFor(null)} label="Connect platforms" size="md">
          <DialogHead
            title={`Connect ${connectFor.name}`}
            sub="A handle names the account. Signing in is what lets us post to it — a post silently skips any platform that is not connected."
            onClose={() => setConnectFor(null)}
          />
          <DialogBody>
            <OAuthTiles
              account={connectFor}
              onChange={() => {
                load();
                setConnectFor(null);
              }}
            />
          </DialogBody>
          <DialogFoot>
            <GhostButton onClick={() => setConnectFor(null)}>Close</GhostButton>
          </DialogFoot>
        </Dialog>
      )}

      <ConfirmDialog
        open={!!toDeleteBrand}
        onClose={() => setToDeleteBrand(null)}
        onConfirm={() => act(() => deleteBrand(toDeleteBrand!.id), "Brand deleted", "Could not delete that brand", () => setToDeleteBrand(null))}
        busy={busy}
        title="Delete brand?"
        body="A brand does not go alone — its posts and its accounts go with it."
        bullets={[
          `Its ${postCounts[toDeleteBrand?.id ?? -1] ?? 0} posts, their slides and every generated video`,
          `Its ${(toDeleteBrand?.accounts ?? []).length} accounts, their handles and any platform sign-in`,
          "Anything of theirs still scheduled",
        ]}
        keeps={["Posts already published, on the platforms they went to"]}
        note="This is the only action here that cannot be undone from inside the app."
        confirmText={toDeleteBrand?.name}
        confirmLabel="Delete brand"
      />

      <ConfirmDialog
        open={!!toDeleteAccount}
        onClose={() => setToDeleteAccount(null)}
        onConfirm={() =>
          act(() => deleteAccount(toDeleteAccount!.account.id), "Account removed", "Could not remove that account", () =>
            setToDeleteAccount(null),
          )
        }
        busy={busy}
        title="Remove account?"
        body="The account stops receiving new posts. What it has already posted stays up."
        bullets={[
          "Its four handles and any connected platform sign-in",
          "Its slide variations on posts not yet generated",
          ...(toDeleteAccount?.account.role === "master"
            ? ["It is the master — the brand will have none until you make another account the master"]
            : []),
        ]}
        keeps={["Everything it has already posted, on every platform", "The brand and its other accounts"]}
        confirmLabel="Remove account"
      />
    </>
  );
}

function Meta({ label, children, wide }: { label: string; children: React.ReactNode; wide?: boolean }) {
  return (
    <div className={`rounded-[12px] border border-border bg-secondary px-3 py-2.5 ${wide ? "col-span-2" : ""}`}>
      <span className="mb-[5px] block text-[10px] font-bold uppercase leading-normal tracking-[0.08em] text-subtle">
        {label}
      </span>
      <span className="flex flex-wrap items-center gap-[7px] text-[12.5px] font-semibold tabular-nums leading-normal text-foreground">
        {children}
      </span>
    </div>
  );
}

function AccountRow({
  account,
  onEdit,
  onConnect,
  onDelete,
  onMakeMaster,
}: {
  account: Account;
  onEdit: () => void;
  onConnect: () => void;
  onDelete: () => void;
  onMakeMaster: () => void;
}) {
  const named = PLATS.filter((p) => handleOf(account, p));
  const isMaster = account.role === "master";

  return (
    <div className="border-b border-line-2 py-3 last:border-b-0">
      <div className="flex flex-wrap items-center gap-2.5">
        <div className="min-w-0">
          <div className="text-[13px] font-semibold leading-normal">{account.name}</div>
          <div className="mt-px text-[11px] leading-normal text-subtle">
            {named.length} of {PLATS.length} platforms linked
          </div>
        </div>
        <Tag tone={isMaster ? "done" : "draft"}>{isMaster ? "Master" : "Variation"}</Tag>
        <DotsMenu
          label={`${account.name} actions`}
          items={[
            { icon: FileText, label: "Edit handles", onClick: onEdit },
            { icon: Copy, label: "Reconnect platforms", onClick: onConnect },
            ...(isMaster ? [] : ([{ icon: Copy, label: "Make this the master", onClick: onMakeMaster }] as const)),
            "-",
            { icon: Trash2, label: "Remove account", danger: true, onClick: onDelete },
          ]}
        />
      </div>

      <div className="mt-2.5 flex flex-wrap gap-2">
        {PLATS.map((p) => {
          const h = handleOf(account, p);
          const on = connected(account, p);
          return (
            <span
              key={p}
              title={
                h
                  ? `${PLAT_NAME[p]}: @${h}${on ? " — connected" : " — saved, but not connected, so posts skip it"}`
                  : `No ${PLAT_NAME[p]} handle`
              }
              className={`inline-flex items-center gap-[7px] rounded-[9px] border px-2.5 py-[5px] text-[11.5px] font-semibold leading-normal ${
                h ? "border-border bg-card text-foreground" : "border-border bg-secondary text-subtle"
              }`}
            >
              <PlatformIcon platform={p} className={`h-[13px] w-[13px] ${h ? "" : "opacity-60"}`} />
              {h ? `@${h}` : "Not linked"}
            </span>
          );
        })}
      </div>
    </div>
  );
}

function BrandDialog({ brand, onClose, onSaved }: { brand?: Brand; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(brand?.name ?? "");
  const [slug, setSlug] = useState(brand?.slug ?? "");
  const [colour, setColour] = useState(brand?.background_color ?? "#d4fb78");
  const [tz, setTz] = useState(brand?.timezone ?? "US/Eastern");
  const [times, setTimes] = useState<string[]>(
    (brand?.default_post_times || "09:00,13:00,18:00").split(",").map((t) => t.trim()).filter(Boolean),
  );
  const [adding, setAdding] = useState("");
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true);
    try {
      const body = {
        name,
        slug,
        background_color: colour,
        timezone: tz,
        default_post_times: times.join(","),
      };
      if (brand) await updateBrand(brand.id, body);
      else await createBrand(body);
      toast.success(brand ? "Brand saved" : "Brand created");
      onSaved();
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not save the brand"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open onClose={onClose} label={brand ? "Edit brand" : "New brand"} size="md">
      <DialogHead
        title={brand ? "Edit brand" : "New brand"}
        sub="The look every post from this brand is built in, and when it goes out by default."
        onClose={onClose}
      />
      <DialogBody>
        <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
          <Field label="Name">
            <Input
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                if (!brand) setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, ""));
              }}
              placeholder="Autobrush"
            />
          </Field>
          <Field label="Slug">
            <Input value={slug} onChange={(e) => setSlug(e.target.value)} className="font-mono" placeholder="autobrush" />
          </Field>
        </div>
        <Hint>The slug names the folder its files are written to. Changing it does not move what is already there.</Hint>

        <div className="mt-3.5 grid grid-cols-1 gap-2.5 sm:grid-cols-2">
          <Field label="Background colour">
            <span className="flex items-center gap-2.5">
              <input
                type="color"
                value={colour}
                onChange={(e) => setColour(e.target.value)}
                aria-label="Background colour"
                className="h-9 w-9 flex-none cursor-pointer rounded-[10px] border border-border bg-card p-1"
              />
              <Input value={colour} onChange={(e) => setColour(e.target.value)} className="font-mono" />
            </span>
          </Field>
          <Field label="Timezone">
            <Input value={tz} onChange={(e) => setTz(e.target.value)} placeholder="US/Eastern" />
          </Field>
        </div>

        <div className="mt-[18px] mb-2 text-[10.5px] font-bold uppercase leading-normal tracking-[0.09em] text-subtle">
          Default posting times
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {times.map((t) => (
            <span
              key={t}
              className="inline-flex items-center gap-1 rounded-full border border-border bg-card py-1.5 pl-[11px] pr-1.5 text-[12.5px] font-semibold tabular-nums leading-normal"
            >
              {t}
              <button
                type="button"
                onClick={() => setTimes((ts) => ts.filter((x) => x !== t))}
                aria-label={`Remove ${t}`}
                className="grid h-[18px] w-[18px] place-items-center rounded-[5px] text-subtle hover:bg-secondary hover:text-destructive"
              >
                <X className="h-[11px] w-[11px]" />
              </button>
            </span>
          ))}
          <label className="inline-flex items-center gap-1.5 rounded-full border border-dashed border-border px-[11px] py-1.5 text-[12.5px] font-semibold text-muted-foreground">
            <Plus className="h-3 w-3" />
            <input
              type="time"
              value={adding}
              onChange={(e) => {
                const v = e.target.value;
                setAdding("");
                if (v && !times.includes(v)) setTimes((ts) => [...ts, v].sort());
              }}
              aria-label="Add a time"
              className="w-[92px] bg-transparent outline-none"
            />
          </label>
        </div>
        <Hint>
          A new post picks the next of these that has not passed. They are in the brand&apos;s own timezone, not yours.
        </Hint>
      </DialogBody>
      <DialogFoot note="Applies to new posts — nothing already scheduled moves">
        <GhostButton onClick={onClose}>Cancel</GhostButton>
        <PrimaryButton onClick={save} disabled={!name.trim() || !slug.trim() || busy}>
          {busy ? "Saving…" : "Save brand"}
        </PrimaryButton>
      </DialogFoot>
    </Dialog>
  );
}

function AccountDialog({
  brand,
  account,
  master,
  onClose,
  onSaved,
}: {
  brand: Brand;
  account?: Account;
  master?: Account;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(account?.name ?? "");
  const [role, setRole] = useState(account?.role ?? (master ? "variation" : "master"));
  const [handles, setHandles] = useState<Record<Plat, string>>(
    () => Object.fromEntries(PLATS.map((p) => [p, account ? handleOf(account, p) ?? "" : ""])) as Record<Plat, string>,
  );
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true);
    try {
      const body: Record<string, string> = { name, role };
      PLATS.forEach((p) => (body[`${p}_handle`] = handles[p]));
      if (account) await updateAccount(account.id, body);
      else await createAccount(brand.id, body as never);
      // One master per brand, so promoting demotes the previous holder.
      if (role === "master" && master && master.id !== account?.id) {
        await updateAccount(master.id, { role: "variation" });
      }
      toast.success(account ? "Account saved" : "Account added");
      onSaved();
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not save the account"));
    } finally {
      setBusy(false);
    }
  };

  const demoted = role === "master" && master && master.id !== account?.id ? master.name : null;

  return (
    <Dialog open onClose={onClose} label={account ? "Edit account" : "Add account"} size="md">
      <DialogHead
        title={account ? "Edit account" : `Add an account to ${brand.name}`}
        sub="One account posts to four platforms. A handle here is what the poster signs in as."
        onClose={onClose}
      />
      <DialogBody>
        <Field label="Account name">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Finds By Mia" />
        </Field>

        <div className="mb-2 mt-4 text-[10.5px] font-bold uppercase leading-normal tracking-[0.09em] text-subtle">
          Role
        </div>
        <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
          {(
            [
              { key: "master", title: "Master", body: "Posts the original slides, untouched.", tag: "One per brand" },
              { key: "variation", title: "Variation", body: "Posts its own version of each slide.", tag: "Any number" },
            ] as const
          ).map((opt) => {
            const on = role === opt.key;
            return (
              <button
                key={opt.key}
                type="button"
                onClick={() => setRole(opt.key)}
                aria-pressed={on}
                className={`flex flex-col items-start gap-1 rounded-[13px] border px-3.5 py-3 text-left transition-colors ${
                  on ? "border-primary shadow-[0_0_0_1px_var(--color-primary)]" : "border-border hover:bg-secondary"
                }`}
              >
                <span
                  className={`grid h-[30px] w-[30px] place-items-center rounded-[9px] border ${
                    on ? "border-primary bg-primary text-primary-foreground" : "border-border bg-secondary text-subtle"
                  }`}
                >
                  {opt.key === "master" ? <TagIcon className="h-[14px] w-[14px]" /> : <Copy className="h-[14px] w-[14px]" />}
                </span>
                <span className="mt-0.5 text-[13px] font-bold leading-normal">{opt.title}</span>
                <span className="text-[11px] leading-[1.45] text-subtle">{opt.body}</span>
                <span className="mt-0.5 rounded-full border border-border bg-secondary px-2 py-px text-[10px] font-semibold leading-normal text-subtle">
                  {opt.tag}
                </span>
              </button>
            );
          })}
        </div>
        {demoted && (
          <Hint>
            {brand.name} already has a master. Making this one the master moves <b>{demoted}</b> to variation.
          </Hint>
        )}

        <div className="mb-2 mt-[18px] text-[10.5px] font-bold uppercase leading-normal tracking-[0.09em] text-subtle">
          Handles
        </div>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {PLATS.map((p) => (
            <label key={p} className="flex items-center gap-2">
              <span
                title={PLAT_NAME[p]}
                className="grid h-9 w-9 flex-none place-items-center rounded-[10px] border border-border bg-secondary text-muted-foreground"
              >
                <PlatformIcon platform={p} className="h-[15px] w-[15px]" />
              </span>
              <Input
                value={handles[p]}
                onChange={(e) => setHandles((h) => ({ ...h, [p]: e.target.value }))}
                placeholder="handle, without the @"
              />
            </label>
          ))}
        </div>
        <Hint>
          A handle names the account. Posting to it also needs the platform connected, which is a separate sign-in.
        </Hint>
      </DialogBody>
      <DialogFoot>
        <GhostButton onClick={onClose}>Cancel</GhostButton>
        <PrimaryButton onClick={save} disabled={!name.trim() || busy}>
          {busy ? "Saving…" : "Save account"}
        </PrimaryButton>
      </DialogFoot>
    </Dialog>
  );
}
