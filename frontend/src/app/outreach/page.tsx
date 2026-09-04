"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Plus,
  Send,
  Trash2,
  Users,
  FileText,
  CheckCircle2,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";
import {
  listOutreachCampaigns,
  createOutreachCampaign,
  deleteOutreachCampaign,
  listOutreachTemplates,
  listOutreachAccounts,
  type OutreachCampaign,
  type OutreachTemplate,
  type OutreachAccount,
} from "@/lib/api";
import { ConfirmModal } from "@/components/ui/confirm-modal";
import { StatusPill, ProgressBar, inputClass, apiErrorMessage } from "./ui";

export default function OutreachPage() {
  const [campaigns, setCampaigns] = useState<OutreachCampaign[]>([]);
  const [templates, setTemplates] = useState<OutreachTemplate[]>([]);
  const [accounts, setAccounts] = useState<OutreachAccount[]>([]);
  const [showNew, setShowNew] = useState(false);
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<{ id: number; name: string } | null>(
    null,
  );
  const [deleting, setDeleting] = useState(false);
  const [form, setForm] = useState({
    name: "",
    description: "",
    message_template: "Hi {{username}}, we came across your content and wanted to reach out about {{offer}}.",
    template_id: "",
    offer: "",
  });

  const load = () => {
    listOutreachCampaigns().then(setCampaigns).catch(() => toast.error("Failed to load campaigns"));
    listOutreachTemplates().then(setTemplates).catch(() => {});
    listOutreachAccounts().then(setAccounts).catch(() => {});
  };

  useEffect(() => {
    load();
  }, []);

  const handleCreate = async () => {
    if (!form.name.trim()) return toast.error("Campaign name is required");
    setSaving(true);
    try {
      const created = await createOutreachCampaign({
        name: form.name.trim(),
        description: form.description.trim() || undefined,
        message_template: form.message_template,
        template_id: form.template_id ? Number(form.template_id) : null,
        template_vars: form.offer.trim() ? { offer: form.offer.trim() } : undefined,
      });
      setShowNew(false);
      setForm({ ...form, name: "", description: "", offer: "" });
      load();
      toast.success(`Campaign “${created.name}” created`);
    } catch (e) {
      toast.error(apiErrorMessage(e, "Failed to create campaign"));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!confirmDelete) return;
    setDeleting(true);
    try {
      await deleteOutreachCampaign(confirmDelete.id);
      setConfirmDelete(null);
      load();
      toast.success("Campaign deleted");
    } catch (e) {
      toast.error(apiErrorMessage(e, "Failed to delete"));
    } finally {
      setDeleting(false);
    }
  };

  const enabledAccounts = accounts.filter((a) => a.enabled && a.status !== "paused").length;

  return (
    <div className="mx-auto max-w-6xl">
      <div className="mb-6 md:mb-8 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-foreground">
            <Send className="h-5 w-5 text-background" />
          </div>
          <div>
            <h1 className="text-xl md:text-2xl font-bold tracking-tight">Outreach</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Import creator lists, queue DMs, and watch them go out across your sending accounts.
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Link
            href="/outreach/accounts"
            className="inline-flex min-h-[44px] items-center justify-center gap-2 rounded-lg border border-border px-4 py-2.5 text-sm font-medium transition-colors hover:bg-muted"
          >
            <Users className="h-4 w-4" /> Accounts
            <span className="rounded-full bg-muted px-1.5 text-[11px]">{enabledAccounts}</span>
          </Link>
          <Link
            href="/outreach/templates"
            className="inline-flex min-h-[44px] items-center justify-center gap-2 rounded-lg border border-border px-4 py-2.5 text-sm font-medium transition-colors hover:bg-muted"
          >
            <FileText className="h-4 w-4" /> Templates
          </Link>
          <button
            onClick={() => setShowNew(true)}
            className="inline-flex min-h-[44px] items-center justify-center gap-2 rounded-lg bg-foreground px-5 py-2.5 text-sm font-medium text-background transition-opacity hover:opacity-90"
          >
            <Plus className="h-4 w-4" /> New Campaign
          </button>
        </div>
      </div>

      {accounts.length === 0 && (
        <div className="mb-6 rounded-xl border border-border bg-card p-4 text-sm">
          <p className="font-medium">No sending accounts yet.</p>
          <p className="mt-1 text-muted-foreground">
            A campaign needs at least one enabled account to send from.{" "}
            <Link href="/outreach/accounts" className="underline">
              Add one
            </Link>
            .
          </p>
        </div>
      )}

      {campaigns.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border p-10 text-center">
          <Send className="mx-auto h-8 w-8 text-muted-foreground" />
          <p className="mt-3 text-sm font-medium">No campaigns yet</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Create one, import a list of profiles, then press Start.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {campaigns.map((c) => (
            <div
              key={c.id}
              className="rounded-xl border border-border bg-card p-4 md:p-5 transition-colors hover:border-foreground/30"
            >
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <Link
                      href={`/outreach/${c.id}`}
                      className="truncate text-base font-semibold hover:underline"
                    >
                      {c.name}
                    </Link>
                    <StatusPill status={c.status} />
                  </div>
                  {c.description && (
                    <p className="mt-1 line-clamp-1 text-sm text-muted-foreground">
                      {c.description}
                    </p>
                  )}
                  <p className="mt-1 text-xs text-muted-foreground">
                    Created {new Date(c.created_at).toLocaleDateString()}
                  </p>
                </div>
                <button
                  onClick={() => setConfirmDelete({ id: c.id, name: c.name })}
                  aria-label={`Delete ${c.name}`}
                  className="self-start rounded-md p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-destructive"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>

              <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
                <Stat label="Targets" value={c.total_targets} />
                <Stat label="Processed" value={c.processed_count} />
                <Stat
                  label="Successful"
                  value={c.successful_count}
                  icon={<CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />}
                />
                <Stat
                  label="Failed"
                  value={c.failed_count}
                  icon={<XCircle className="h-3.5 w-3.5 text-destructive" />}
                />
              </div>

              <div className="mt-4">
                <ProgressBar
                  processed={c.processed_count}
                  total={c.total_targets}
                  successful={c.successful_count}
                />
              </div>
            </div>
          ))}
        </div>
      )}

      {showNew && (
        <div
          className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/50 backdrop-blur-sm p-4"
          onClick={() => setShowNew(false)}
        >
          <div
            className="w-full max-w-lg max-h-[90vh] overflow-y-auto rounded-2xl bg-card p-5 md:p-6 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 className="mb-5 text-lg font-semibold">New Campaign</h2>
            <div className="space-y-4">
              <div>
                <label className="mb-1.5 block text-sm font-medium">Name</label>
                <input
                  className={inputClass}
                  placeholder="e.g. Q3 creator outreach"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                />
              </div>
              <div>
                <label className="mb-1.5 block text-sm font-medium">Description</label>
                <input
                  className={inputClass}
                  placeholder="Optional"
                  value={form.description}
                  onChange={(e) => setForm({ ...form, description: e.target.value })}
                />
              </div>
              {templates.length > 0 && (
                <div>
                  <label className="mb-1.5 block text-sm font-medium">Start from a template</label>
                  <select
                    className={inputClass}
                    value={form.template_id}
                    onChange={(e) => {
                      const id = e.target.value;
                      const chosen = templates.find((t) => String(t.id) === id);
                      setForm({
                        ...form,
                        template_id: id,
                        message_template: chosen ? chosen.body : form.message_template,
                      });
                    }}
                  >
                    <option value="">— none —</option>
                    {templates.map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.name}
                      </option>
                    ))}
                  </select>
                </div>
              )}
              <div>
                <label className="mb-1.5 block text-sm font-medium">Message</label>
                <textarea
                  rows={4}
                  className={inputClass}
                  value={form.message_template}
                  onChange={(e) => setForm({ ...form, message_template: e.target.value })}
                />
                <p className="mt-1 text-xs text-muted-foreground">
                  {"Use {{username}}, {{profile_url}}, {{campaign_name}}, {{account_name}} — plus any variable you define below."}
                </p>
              </div>
              {form.message_template.includes("{{offer}}") && (
                <div>
                  <label className="mb-1.5 block text-sm font-medium">
                    {"Value for {{offer}}"}
                  </label>
                  <input
                    className={inputClass}
                    placeholder="e.g. our creator program"
                    value={form.offer}
                    onChange={(e) => setForm({ ...form, offer: e.target.value })}
                  />
                </div>
              )}
            </div>
            <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button
                onClick={() => setShowNew(false)}
                className="min-h-[44px] rounded-lg border border-border px-5 text-sm font-medium transition-colors hover:bg-muted"
              >
                Cancel
              </button>
              <button
                onClick={handleCreate}
                disabled={saving}
                className="min-h-[44px] rounded-lg bg-foreground px-5 text-sm font-medium text-background transition-opacity hover:opacity-90 disabled:opacity-50"
              >
                {saving ? "Creating…" : "Create campaign"}
              </button>
            </div>
          </div>
        </div>
      )}

      <ConfirmModal
        open={confirmDelete !== null}
        onOpenChange={(open) => !open && setConfirmDelete(null)}
        title="Delete campaign?"
        description={`“${confirmDelete?.name}” and all of its targets, jobs and results will be removed. This cannot be undone.`}
        confirmLabel="Delete"
        variant="danger"
        loading={deleting}
        onConfirm={handleDelete}
      />
    </div>
  );
}

function Stat({
  label,
  value,
  icon,
}: {
  label: string;
  value: number;
  icon?: React.ReactNode;
}) {
  return (
    <div className="rounded-lg bg-muted/50 px-3 py-2">
      <p className="flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-muted-foreground">
        {icon}
        {label}
      </p>
      <p className="mt-0.5 text-lg font-semibold tabular-nums">{value.toLocaleString()}</p>
    </div>
  );
}
