"use client";

/**
 * Message templates — reusable bodies with placeholders.
 *
 * A grid rather than a table: a template is read, not compared, and the
 * thing worth seeing at a glance is the message itself. Each card shows
 * the body, the placeholders it uses, and whether any campaign depends on
 * it — the last of which is what makes editing or deleting one safe or
 * not.
 */

import { useEffect, useMemo, useState } from "react";
import { Copy, FileText, Plus, Search, Send, Trash2, Users } from "lucide-react";
import { toast } from "sonner";
import {
  createOutreachTemplate,
  deleteOutreachTemplate,
  listOutreachCampaigns,
  listOutreachTemplates,
  type OutreachCampaign,
  type OutreachTemplate,
} from "@/lib/api";
import {
  BackLink,
  Card,
  Chip,
  DotsMenu,
  Empty,
  MenuItem,
  n,
  Note,
  PageActions,
  PageHead,
  PageTitle,
  PrimaryButton,
  Tabs,
} from "@/components/kit";
import { ConfirmDialog } from "@/components/kit/dialog";
import { TemplateDialog } from "@/components/outreach/template-dialog";
import { extractVariables } from "@/components/outreach/template";
import { apiErrorMessage } from "@/components/kit/format";

export default function OutreachTemplatesPage() {
  const [templates, setTemplates] = useState<OutreachTemplate[] | null>(null);
  const [campaigns, setCampaigns] = useState<OutreachCampaign[]>([]);
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);

  const [editing, setEditing] = useState<OutreachTemplate | null>(null);
  const [showEditor, setShowEditor] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<OutreachTemplate | null>(null);
  const [deleting, setDeleting] = useState(false);

  const load = () =>
    listOutreachTemplates()
      .then(setTemplates)
      .catch((e) => {
        setTemplates([]);
        toast.error(apiErrorMessage(e, "Failed to load templates"));
      });

  useEffect(() => {
    load();
    // Campaign rows are what "used by" is counted from, and what makes a
    // delete consequential rather than tidy-up.
    listOutreachCampaigns().then(setCampaigns).catch(() => {});
  }, []);

  const usedBy = useMemo(() => {
    const c: Record<number, number> = {};
    for (const x of campaigns) if (x.template_id) c[x.template_id] = (c[x.template_id] ?? 0) + 1;
    return c;
  }, [campaigns]);

  const all = templates ?? [];
  const inUse = all.filter((t) => (usedBy[t.id] ?? 0) > 0);
  const unused = all.filter((t) => (usedBy[t.id] ?? 0) === 0);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return all.filter((t) => {
      const okFilter =
        filter === "all" || (filter === "used" ? (usedBy[t.id] ?? 0) > 0 : (usedBy[t.id] ?? 0) === 0);
      const okQuery = !q || t.name.toLowerCase().includes(q) || t.body.toLowerCase().includes(q);
      return okFilter && okQuery;
    });
  }, [templates, filter, query, usedBy]); // eslint-disable-line react-hooks/exhaustive-deps

  const openNew = () => {
    setEditing(null);
    setShowEditor(true);
  };

  const duplicate = async (t: OutreachTemplate) => {
    try {
      let defaults: Record<string, string> | undefined;
      if (t.defaults) {
        try {
          defaults = JSON.parse(t.defaults);
        } catch {
          // A defaults blob that will not parse is dropped rather than
          // carried into the copy as a broken string.
        }
      }
      const made = await createOutreachTemplate({ name: `${t.name} (copy)`, body: t.body, defaults });
      await load();
      toast.success(`“${made.name}” created`);
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not duplicate"));
    }
  };

  const doDelete = async () => {
    if (!confirmDelete) return;
    setDeleting(true);
    try {
      await deleteOutreachTemplate(confirmDelete.id);
      setConfirmDelete(null);
      await load();
      toast.success("Template deleted");
    } catch (e) {
      toast.error(apiErrorMessage(e, "Failed to delete"));
    } finally {
      setDeleting(false);
    }
  };

  const cardMenu = (t: OutreachTemplate): MenuItem[] => [
    {
      label: "Edit template",
      icon: FileText,
      onClick: () => {
        setEditing(t);
        setShowEditor(true);
      },
    },
    { label: "Duplicate", icon: Copy, onClick: () => duplicate(t) },
    {
      label: "Copy message text",
      icon: Send,
      onClick: () => {
        void navigator.clipboard.writeText(t.body);
        toast.success("Message copied");
      },
    },
    "-",
    { label: "Delete template", icon: Trash2, danger: true, onClick: () => setConfirmDelete(t) },
  ];

  const loading = templates === null;

  return (
    <div className="flex flex-col gap-4" data-metrics>
      <BackLink href="/outreach">Outreach</BackLink>

      <PageHead>
        <PageTitle
          title="Message templates"
          sub="Reusable message bodies with placeholders, so a campaign does not start from a blank box."
        />
        <PageActions>
          <Chip icon={Users} href="/outreach/accounts">
            Accounts
          </Chip>
          <PrimaryButton icon={Plus} onClick={openNew}>
            New template
          </PrimaryButton>
        </PageActions>
      </PageHead>

      {all.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <Tabs
            value={filter}
            onChange={setFilter}
            items={[
              { key: "all", label: "All", count: all.length },
              { key: "used", label: "In use", count: inUse.length },
              { key: "unused", label: "Unused", count: unused.length },
            ]}
          />
          <div className="ml-auto">
            {searching || query ? (
              <div className="flex items-center gap-[7px] rounded-[11px] border border-border bg-card px-[13px] py-2 shadow-card">
                <Search className="h-3.5 w-3.5 flex-none text-subtle" />
                <input
                  autoFocus
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onBlur={() => !query && setSearching(false)}
                  placeholder="Search templates"
                  className="w-[150px] border-0 bg-transparent text-[12.5px] leading-normal text-foreground outline-none placeholder:text-subtle"
                />
              </div>
            ) : (
              <Chip icon={Search} onClick={() => setSearching(true)}>
                Search templates
              </Chip>
            )}
          </div>
        </div>
      )}

      {loading ? (
        <Card>
          <div className="p-4 text-[12.5px] leading-normal text-subtle">Loading templates…</div>
        </Card>
      ) : rows.length === 0 ? (
        <Card>
          <Empty
            icon={FileText}
            title={all.length === 0 ? "No templates yet" : "No templates match"}
            action={
              all.length === 0 ? (
                <PrimaryButton icon={Plus} onClick={openNew}>
                  Write your first template
                </PrimaryButton>
              ) : undefined
            }
          >
            {all.length === 0 ? (
              <>
                A template holds the message body and its placeholders —{" "}
                <b className="font-mono text-[11px] font-semibold text-muted-foreground">{"{{username}}"}</b> for the
                creator&apos;s handle,{" "}
                <b className="font-mono text-[11px] font-semibold text-muted-foreground">{"{{offer}}"}</b> for whatever
                you are pitching. Write it once and every campaign can reuse it.
              </>
            ) : (
              "Change the filter or the search, or write a new one."
            )}
          </Empty>
        </Card>
      ) : (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(340px,1fr))] gap-4">
          {rows.map((t) => {
            const vars = extractVariables(t.body);
            const used = usedBy[t.id] ?? 0;
            return (
              <Card key={t.id} className="flex flex-col px-[18px] pb-3.5 pt-4">
                <div className="mb-[11px] flex items-center gap-2.5">
                  <span className="min-w-0 truncate text-[13.5px] font-bold leading-normal text-foreground">
                    {t.name}
                  </span>
                  <span className="ml-auto flex-none">
                    <DotsMenu label={`Actions for ${t.name}`} items={cardMenu(t)} />
                  </span>
                </div>
                <div className="min-h-[74px] whitespace-pre-wrap break-words rounded-[12px] border border-border bg-secondary px-3.5 py-3 text-[12.5px] leading-[1.55] text-muted-foreground">
                  {t.body}
                </div>
                <div className="mt-[11px] flex flex-wrap items-center gap-2.5">
                  <span className="flex flex-wrap gap-1.5">
                    {vars.map((v) => (
                      <span
                        key={v}
                        className="rounded-[6px] bg-chart-2/12 px-1.5 py-0.5 font-mono text-[10.5px] font-semibold leading-normal text-chart-2"
                      >
                        {`{{${v}}}`}
                      </span>
                    ))}
                  </span>
                  <span className="ml-auto whitespace-nowrap text-[11px] leading-normal text-subtle">
                    {used ? `Used by ${used} campaign${used === 1 ? "" : "s"}` : "Not used yet"} ·{" "}
                    {t.created_at.slice(0, 10)}
                  </span>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      {all.length > 0 && (
        <Note>
          A placeholder with no value at send time stops the campaign rather than sending the raw{" "}
          <b className="font-mono font-semibold text-muted-foreground">{"{{token}}"}</b> to a real person.
        </Note>
      )}

      <TemplateDialog
        open={showEditor}
        onClose={() => setShowEditor(false)}
        template={editing}
        usedBy={editing ? (usedBy[editing.id] ?? 0) : 0}
        onSaved={load}
      />

      <ConfirmDialog
        open={confirmDelete !== null}
        onClose={() => setConfirmDelete(null)}
        onConfirm={doDelete}
        title="Delete template?"
        confirmLabel="Delete template"
        busy={deleting}
        body={
          <>
            <b className="font-bold text-foreground">“{confirmDelete?.name}”</b> is removed from the template list.
            {confirmDelete && (usedBy[confirmDelete.id] ?? 0) > 0 ? (
              <>
                {" "}
                It is used by{" "}
                <b className="font-bold text-foreground">
                  {n(usedBy[confirmDelete.id])} campaign
                  {usedBy[confirmDelete.id] === 1 ? "" : "s"}
                </b>
                .
              </>
            ) : null}
          </>
        }
        bullets={[
          "Campaigns already created from it keep their own copy of the message — none of them stop sending",
          "New campaigns can no longer start from it",
          "Any image attached to the template is deleted with it",
        ]}
      />
    </div>
  );
}
