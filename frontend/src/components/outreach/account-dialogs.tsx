"use client";

/**
 * Adding an account, and getting a session onto it.
 *
 * Neither path needs a browser on the operator's own machine, which is the
 * whole point:
 *
 *  - **Sign in here** opens a real browser on the backend and streams its
 *    screen into this dialog over a one-time viewer ticket. You type into
 *    the platform's own login page; only the resulting session comes back,
 *    encrypted. 2FA and checkpoints work because it is the real site.
 *  - **Paste a session** takes a Playwright storage state and stores it.
 *    No browser opens at all.
 *
 * OAuth is not a third option, and will not become one: Instagram's
 * messaging API only answers inside a 24-hour reply window, TikTok has no
 * DM API, and X's is paywalled.
 *
 * Adding is two steps because the backend is: an account row has to exist
 * before a session can hang off it.
 */

import { useEffect, useState } from "react";
import { Info, Plus, Shield } from "lucide-react";
import { toast } from "sonner";
import {
  createOutreachAccount,
  getBrowserLoginState,
  setOutreachAccountSession,
  startBrowserLogin,
  testAccountProxy,
  updateOutreachAccount,
  type BrowserLoginState,
  type OutreachAccount,
  type ProxyCheck,
} from "@/lib/api";
import { SessionViewer } from "./SessionViewer";
import {
  Dialog,
  DialogBody,
  DialogFoot,
  DialogHead,
  Field,
  FieldLabel,
  GhostButton,
  Hint,
  Input,
  Radio,
  Textarea,
} from "@/components/kit/dialog";
import { PLATFORMS, PLATFORM_LABEL, PlatformIcon, PrimaryButton, Tag } from "@/components/kit";
import { apiErrorMessage } from "@/components/kit/format";

/* ------------------------------------------------------------------ */
/* add                                                                 */
/* ------------------------------------------------------------------ */

export function AddAccountDialog({
  open,
  onClose,
  defaultPlatform = "tiktok",
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  defaultPlatform?: string;
  /** Called with the new account and whether to go straight to sign-in. */
  onCreated: (account: OutreachAccount, signIn: boolean) => void;
}) {
  const [platform, setPlatform] = useState(defaultPlatform);
  const [name, setName] = useState("");
  const [purpose, setPurpose] = useState("sending");
  const [way, setWay] = useState<"live" | "paste">("live");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setPlatform(defaultPlatform);
    setName("");
    setPurpose("sending");
    setWay("live");
  }, [open, defaultPlatform]);

  const create = async () => {
    if (!name.trim()) return toast.error("Give the account a name");
    setBusy(true);
    try {
      const made = await createOutreachAccount({ name: name.trim(), platform, purpose });
      onCreated(made, way === "live");
    } catch (e) {
      toast.error(apiErrorMessage(e, "Failed to add account"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} label="Add a sending account">
      <DialogHead
        title="Add a sending account"
        sub="Campaigns send from these. Your password never reaches this service — only the signed-in session is stored, encrypted."
        onClose={onClose}
      />
      <DialogBody>
        <FieldLabel>Platform</FieldLabel>
        <div className="grid grid-cols-3 gap-[9px]">
          {PLATFORMS.map((p) => {
            const on = p === platform;
            return (
              <button
                key={p}
                type="button"
                onClick={() => setPlatform(p)}
                aria-pressed={on}
                className={`flex flex-col items-center gap-2 rounded-[13px] border bg-card px-2 py-3.5 text-[12.5px] font-semibold leading-normal transition-colors ${
                  on ? "border-primary shadow-[0_0_0_1px_var(--primary)]" : "border-border hover:bg-secondary"
                }`}
              >
                <span
                  className={`grid h-[34px] w-[34px] place-items-center rounded-[10px] border ${
                    on ? "border-primary bg-primary text-primary-foreground" : "border-border bg-secondary text-foreground"
                  }`}
                >
                  <PlatformIcon platform={p} className="h-[17px] w-[17px]" />
                </span>
                {PLATFORM_LABEL[p]}
              </button>
            );
          })}
        </div>

        <Field label="Name it" className="mt-4">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Mia — Instagram" />
        </Field>
        <Hint>Only you see this. It labels the account in campaign lists and logs.</Hint>

        <FieldLabel className="mt-[18px]">What it is for</FieldLabel>
        <div className="flex flex-col gap-2">
          <Radio checked={purpose === "sending"} onChange={() => setPurpose("sending")}>
            <span className="text-[13px] font-bold leading-normal text-foreground">Sending messages</span>
            <span className="text-[11.5px] leading-[1.45] text-subtle">
              Campaigns lease it to send. Its budget is what your outreach spends.
            </span>
          </Radio>
          <Radio checked={purpose === "discovery"} onChange={() => setPurpose("discovery")}>
            <span className="text-[13px] font-bold leading-normal text-foreground">Finding profiles</span>
            <span className="text-[11.5px] leading-[1.45] text-subtle">
              Opens a great many pages quickly, which is the likelier way to get restricted. It is never leased to send.
            </span>
          </Radio>
        </div>

        <FieldLabel className="mt-[18px]">Sign in</FieldLabel>
        <div className="flex flex-col gap-2">
          <Radio
            checked={way === "live"}
            onChange={() => setWay("live")}
            right={
              <span className="ml-auto flex-none">
                <Tag tone="done">Recommended</Tag>
              </span>
            }
          >
            <span className="flex items-center gap-1.5 text-[13px] font-bold leading-normal text-foreground">
              Sign in here <Shield className="h-3.5 w-3.5 text-subtle" />
            </span>
            <span className="text-[11.5px] leading-[1.45] text-subtle">
              A real browser opens inside this page. You log in as normal; the session is captured and encrypted.
              Handles 2FA and checkpoints.
            </span>
          </Radio>
          <Radio checked={way === "paste"} onChange={() => setWay("paste")}>
            <span className="text-[13px] font-bold leading-normal text-foreground">Paste a session</span>
            <span className="text-[11.5px] leading-[1.45] text-subtle">
              Already have a storage-state JSON? Drop it in on the next step. No browser opens at all.
            </span>
          </Radio>
        </div>
      </DialogBody>
      <DialogFoot note="Step 1 of 2 · the session is captured next">
        <GhostButton onClick={onClose} disabled={busy}>
          Cancel
        </GhostButton>
        <PrimaryButton icon={Plus} onClick={create} disabled={busy || !name.trim()}>
          {busy ? "Adding…" : "Add account"}
        </PrimaryButton>
      </DialogFoot>
    </Dialog>
  );
}

/* ------------------------------------------------------------------ */
/* session                                                             */
/* ------------------------------------------------------------------ */

export function SessionDialog({
  account,
  onClose,
  onSaved,
  startLive = false,
}: {
  account: OutreachAccount | null;
  onClose: () => void;
  onSaved: () => void;
  /** Open straight into the streamed sign-in, for a just-created account. */
  startLive?: boolean;
}) {
  const [login, setLogin] = useState<BrowserLoginState | null>(null);
  const [json, setJson] = useState("");
  const [way, setWay] = useState<"live" | "paste">("live");
  const [busy, setBusy] = useState(false);
  // Which window was opened: a sign-in page, or the saved session itself.
  const [opened, setOpened] = useState<"signin" | "saved">("signin");

  // Ask whether this host can open a login window, whenever it opens.
  useEffect(() => {
    if (!account) return setLogin(null);
    setJson("");
    setWay(startLive ? "live" : "live");
    let live = true;
    getBrowserLoginState(account.id)
      .then((s) => live && setLogin(s))
      .catch(() => live && setLogin(null));
    return () => {
      live = false;
    };
  }, [account, startLive]);

  // While a window is open, poll until it resolves. Signing in takes
  // minutes, so the request that started it returned long ago.
  useEffect(() => {
    if (!account || !login?.running) return;
    const iv = setInterval(async () => {
      try {
        const next = await getBrowserLoginState(account.id);
        setLogin(next);
        if (next.capture?.status === "saved") {
          toast.success(next.capture.message);
          onSaved();
          onClose();
        } else if (next.capture?.status === "failed") {
          toast.error(next.capture.message);
        }
      } catch {
        /* keep polling — a dropped poll is not a failed sign-in */
      }
    }, 2000);
    return () => clearInterval(iv);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [account, login?.running]);

  const openSignIn = async () => {
    if (!account) return;
    try {
      const capture = await startBrowserLogin(account.id);
      setOpened("signin");
      setLogin((prev) => (prev ? { ...prev, running: true, capture } : prev));
      toast.success("A browser window is opening — sign in there");
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not open a sign-in window"));
    }
  };

  // The saved session, already signed in, at the inbox — where a message
  // campaign met its verification puzzle. Saved when the window is closed.
  const openSaved = async () => {
    if (!account) return;
    try {
      const capture = await startBrowserLogin(account.id, true);
      setOpened("saved");
      setLogin((prev) => (prev ? { ...prev, running: true, capture } : prev));
      toast.success("A signed-in window is opening — solve any puzzle, then close it");
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not open the signed-in window"));
    }
  };

  const savePasted = async () => {
    if (!account) return;
    setBusy(true);
    try {
      await setOutreachAccountSession(account.id, json);
      toast.success("Session stored (encrypted)");
      onSaved();
      onClose();
    } catch (e) {
      toast.error(apiErrorMessage(e, "Failed to store session"));
    } finally {
      setBusy(false);
    }
  };

  const streaming = !!login?.capture && !login.capture.done;

  return (
    <Dialog open={account !== null} onClose={onClose} label="Attach a session" size={streaming ? "lg" : "md"}>
      <DialogHead
        title={account ? `Sign in as “${account.name}”` : "Sign in"}
        sub="Only the signed-in session is stored, and it is encrypted before it is written. Your password never reaches this service."
        onClose={onClose}
      />
      <DialogBody>
        {login && !login.available && (
          <div className="mb-3 flex items-start gap-2 rounded-[12px] border border-warn/40 bg-warn/10 px-3.5 py-3 text-[12px] leading-[1.5] text-muted-foreground">
            <Info className="mt-0.5 h-3.5 w-3.5 flex-none text-warn" />
            <span>
              {login.unavailable_reason ?? "This host cannot open a sign-in browser."} Paste a session below instead.
            </span>
          </div>
        )}

        {login?.available && (
          <>
            <FieldLabel>How</FieldLabel>
            <div className="mb-4 flex flex-col gap-2">
              <Radio checked={way === "live"} onChange={() => setWay("live")} disabled={streaming}>
                <span className="text-[13px] font-bold leading-normal text-foreground">Sign in here</span>
                <span className="text-[11.5px] leading-[1.45] text-subtle">
                  The platform&apos;s own login screen, streamed into this dialog.
                </span>
              </Radio>
              <Radio checked={way === "paste"} onChange={() => setWay("paste")} disabled={streaming}>
                <span className="text-[13px] font-bold leading-normal text-foreground">Paste a session</span>
                <span className="text-[11.5px] leading-[1.45] text-subtle">A Playwright storage state.</span>
              </Radio>
            </div>
          </>
        )}

        {login?.available && way === "live" && (
          <>
            {streaming ? (
              login!.capture!.on_screen ? (
                <div className="overflow-hidden rounded-[14px] border border-border bg-card">
                  <div className="flex items-center gap-2 border-b border-border px-3 py-2">
                    <span className="flex gap-1">
                      {[0, 1, 2].map((i) => (
                        <i key={i} className="h-[7px] w-[7px] rounded-full bg-border" />
                      ))}
                    </span>
                    <span className="flex items-center gap-1.5 text-[11px] leading-normal text-subtle">
                      <Shield className="h-3 w-3" />
                      {account ? PLATFORM_LABEL[account.platform] ?? account.platform : ""} sign-in
                    </span>
                    <span className="ml-auto">
                      <Tag tone="live">Live</Tag>
                    </span>
                  </div>
                  <div className="flex h-[min(52vh,420px)] flex-col">
                    {account && <SessionViewer accountId={account.id} />}
                  </div>
                </div>
              ) : (
                // Nowhere to stream from: the backend is on a machine with
                // no virtual display, so the sign-in window opened there as
                // a real window.
                <p className="text-[12.5px] leading-[1.55] text-muted-foreground">
                  {opened === "saved"
                    ? login!.capture!.message
                    : "A sign-in window is open on the machine running the backend — sign in there. This closes on its own when it is done."}
                </p>
              )
            ) : (
              <div className="flex flex-col items-center gap-1.5 rounded-[14px] border-[1.5px] border-dashed border-border bg-secondary px-5 py-[26px] text-center">
                <span className="mb-0.5 grid h-[38px] w-[38px] place-items-center rounded-[11px] border border-border bg-card text-muted-foreground">
                  {account && <PlatformIcon platform={account.platform} className="h-[17px] w-[17px]" />}
                </span>
                <span className="text-[13px] font-semibold leading-normal text-foreground">
                  The platform&apos;s own login screen appears here.
                </span>
                <span className="max-w-[46ch] text-[11px] leading-[1.5] text-subtle">
                  You type into the real site. Nothing is keylogged, proxied or stored except the session it hands back.
                </span>
              </div>
            )}
            {login.capture?.status === "failed" && <Hint tone="bad">{login.capture.message}</Hint>}
          </>
        )}

        {(way === "paste" || !login?.available) && (
          <>
            <Textarea
              rows={6}
              value={json}
              onChange={(e) => setJson(e.target.value)}
              placeholder='{"cookies": [ ... ], "origins": [ ... ]}'
            />
            <Hint>
              A Playwright storage state, or any export with <code className="font-mono">cookies</code> and/or{" "}
              <code className="font-mono">origins</code>. It is encrypted before it is written.
            </Hint>
          </>
        )}
      </DialogBody>
      <DialogFoot>
        <GhostButton onClick={onClose} disabled={busy}>
          {streaming ? "Close" : "Cancel"}
        </GhostButton>
        {login?.available && way === "live" && !streaming && account?.has_session && (
          <GhostButton onClick={openSaved}>Open signed-in browser</GhostButton>
        )}
        {login?.available && way === "live" && !streaming ? (
          <PrimaryButton icon={Shield} onClick={openSignIn}>
            Open sign-in
          </PrimaryButton>
        ) : way === "paste" || !login?.available ? (
          <PrimaryButton onClick={savePasted} disabled={busy || !json.trim()}>
            {busy ? "Saving…" : "Store session"}
          </PrimaryButton>
        ) : null}
      </DialogFoot>
    </Dialog>
  );
}

/* ------------------------------------------------------------------ */
/* proxy                                                               */
/* ------------------------------------------------------------------ */

export function ProxyDialog({
  account,
  onClose,
  onSaved,
}: {
  account: OutreachAccount | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [url, setUrl] = useState("");
  const [check, setCheck] = useState<ProxyCheck | null>(null);
  const [checking, setChecking] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setUrl("");
    setCheck(null);
  }, [account]);

  return (
    <Dialog open={account !== null} onClose={onClose} label="Proxy" size="sm">
      <DialogHead
        title={account ? `Proxy for “${account.name}”` : "Proxy"}
        sub="Accounts without one all send from this server’s address, which is what makes a cluster of them look like a cluster."
        onClose={onClose}
      />
      <DialogBody>
        <Input
          className="font-mono"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="http://user:pass@host:port"
        />
        {account?.proxy && !url && (
          <Hint>
            Currently <span className="font-mono text-foreground">{account.proxy}</span>. Leave blank and save to remove
            it.
          </Hint>
        )}
        {check && (
          <div
            className={`mt-3 rounded-[12px] border px-3.5 py-3 text-[12px] leading-[1.5] ${
              check.ok ? "border-good/40 bg-good/10" : "border-warn/40 bg-warn/10"
            }`}
          >
            <p className="font-bold text-foreground">{check.detail}</p>
            <p className="mt-1 text-muted-foreground">
              Seen as <span className="font-mono">{check.egress_ip}</span> · this server is{" "}
              <span className="font-mono">{check.server_ip}</span>
            </p>
          </div>
        )}
      </DialogBody>
      <DialogFoot>
        <GhostButton onClick={onClose} disabled={busy}>
          Cancel
        </GhostButton>
        {/* Only worth offering once something is stored: it asks the live
            proxy for the address the world sees. */}
        {account?.proxy && (
          <GhostButton
            disabled={checking}
            onClick={async () => {
              setChecking(true);
              setCheck(null);
              try {
                setCheck(await testAccountProxy(account.id));
              } catch (e) {
                toast.error(apiErrorMessage(e, "The proxy did not answer"));
              } finally {
                setChecking(false);
              }
            }}
          >
            {checking ? "Checking…" : "Test"}
          </GhostButton>
        )}
        <PrimaryButton
          disabled={busy}
          onClick={async () => {
            if (!account) return;
            setBusy(true);
            try {
              await updateOutreachAccount(account.id, { proxy_url: url.trim() });
              toast.success(url.trim() ? "Proxy saved" : "Proxy removed");
              onSaved();
              onClose();
            } catch (e) {
              toast.error(apiErrorMessage(e, "Could not save that proxy"));
            } finally {
              setBusy(false);
            }
          }}
        >
          {busy ? "Saving…" : "Save"}
        </PrimaryButton>
      </DialogFoot>
    </Dialog>
  );
}

/* ------------------------------------------------------------------ */
/* phone                                                               */
/* ------------------------------------------------------------------ */

/**
 * The phone that does a TikTok account's follows.
 *
 * TikTok's website accepts a follow from these accounts and quietly drops
 * it; the app keeps it. So follows for an account with a phone go through
 * the TikTok app on that phone, and everything else stays in the browser.
 * The handle is a safety catch: the phone is checked to be signed in as it
 * before anything is followed.
 */
/**
 * Switch a TikTok account between the server's browser and the user's phone.
 *
 * On phone, the ICREATEFLOW app does the account's follows inside the TikTok
 * app — where they stick — and no browser sign-in is needed. The app links
 * itself to the account from its Phone tab; until it does, follows wait.
 */
export function SwitchToPhoneDialog({
  account,
  onClose,
  onSaved,
}: {
  account: OutreachAccount | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [handle, setHandle] = useState("");
  const [busy, setBusy] = useState(false);
  const onPhone = account?.via === "phone";

  useEffect(() => {
    setHandle(account?.device_handle ?? "");
  }, [account]);

  const save = async (via: "phone" | "browser") => {
    if (!account) return;
    setBusy(true);
    try {
      await updateOutreachAccount(
        account.id,
        via === "phone" ? { via, device_handle: handle.trim() } : { via },
      );
      toast.success(
        via === "phone"
          ? "Switched to phone — link it from the ICREATEFLOW app"
          : "Switched back to the browser",
      );
      onSaved();
      onClose();
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not switch this account"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={account !== null} onClose={onClose} label="Switch to phone" size="sm">
      <DialogHead
        title={account ? (onPhone ? `“${account.name}” works on a phone` : `Switch “${account.name}” to phone`) : "Switch to phone"}
        sub="The ICREATEFLOW app on your phone does this account’s follows, unfollows and messages inside the TikTok app, where follows stick. No browser sign-in is needed. Phone accounts only do TikTok follows, unfollows and messages (no images) for now."
        onClose={onClose}
      />
      <DialogBody>
        <Field label="TikTok username">
          <Input
            className="font-mono"
            value={handle}
            onChange={(e) => setHandle(e.target.value)}
            placeholder="@username"
          />
          <Hint>
            The account TikTok on the phone is signed in as. The phone checks it before every follow, so it never
            follows from somebody else’s account.
          </Hint>
        </Field>
        <Field label="Then, on the phone">
          <Hint>
            {account?.companion_device
              ? `Linked${account.companion_seen_at ? ` · last seen ${ago(account.companion_seen_at)}` : ""}. Open ICREATEFLOW → Phone → Take follows while a campaign runs.`
              : "Open the ICREATEFLOW app → Phone → Link this account, then Take follows. Until a phone links it, its follows wait."}
          </Hint>
        </Field>
      </DialogBody>
      <DialogFoot>
        {onPhone && (
          <GhostButton onClick={() => save("browser")} disabled={busy}>
            Switch to browser
          </GhostButton>
        )}
        <GhostButton onClick={onClose} disabled={busy}>
          Cancel
        </GhostButton>
        <PrimaryButton disabled={busy || !handle.trim()} onClick={() => save("phone")}>
          {busy ? "Saving…" : onPhone ? "Save" : "Switch to phone"}
        </PrimaryButton>
      </DialogFoot>
    </Dialog>
  );
}

/** "5m ago" — for when the phone last asked for work. */
function ago(iso: string): string {
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  if (mins < 60 * 24) return `${Math.round(mins / 60)}h ago`;
  return `${Math.round(mins / 1440)}d ago`;
}

/* ------------------------------------------------------------------ */
/* rename                                                              */
/* ------------------------------------------------------------------ */

export function RenameAccountDialog({
  account,
  onClose,
  onSaved,
}: {
  account: OutreachAccount | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setName(account?.name ?? "");
  }, [account]);

  const save = async () => {
    if (!account) return;
    const next = name.trim();
    if (!next || next === account.name) return onClose();
    setBusy(true);
    try {
      await updateOutreachAccount(account.id, { name: next });
      toast.success(`Renamed to “${next}”`);
      onSaved();
      onClose();
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not rename this account"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={account !== null} onClose={onClose} label="Rename account" size="sm">
      <DialogHead title="Rename account" onClose={onClose} />
      <DialogBody>
        <Field label="Name">
          <Input
            value={name}
            autoFocus
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void save()}
          />
        </Field>
        <Hint>The name is stored once and read everywhere, so this renames it on every campaign too.</Hint>
      </DialogBody>
      <DialogFoot>
        <GhostButton onClick={onClose} disabled={busy}>
          Cancel
        </GhostButton>
        <PrimaryButton onClick={save} disabled={busy || !name.trim()}>
          {busy ? "Saving…" : "Save"}
        </PrimaryButton>
      </DialogFoot>
    </Dialog>
  );
}
