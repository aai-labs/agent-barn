"use client";

import { useState } from "react";
import { XIcon } from "@/components/icons";
import { useTemplate } from "../hooks/use-template";
import { useCreateTemplate } from "../hooks/use-create-template";
import { useUpdateTemplate } from "../hooks/use-update-template";
import type { AgentTemplateRead } from "../schemas";
import {
  TEMPLATE_FILE_KEYS,
  TemplateFileKey,
  TemplateSourceBadge,
  templateFileLabel,
} from "./hire-dialog-steps";

type TemplateFiles = Record<TemplateFileKey, string>;

const EMPTY_FILES: TemplateFiles = {
  soulMd: "",
  identityMd: "",
  userMd: "",
  toolsMd: "",
  agentsMd: "",
  bootMd: "",
  bootstrapMd: "",
  heartbeatMd: "",
};

function filesFrom(template: AgentTemplateRead): TemplateFiles {
  return {
    soulMd: template.soulMd,
    identityMd: template.identityMd,
    userMd: template.userMd,
    toolsMd: template.toolsMd,
    agentsMd: template.agentsMd,
    bootMd: template.bootMd,
    bootstrapMd: template.bootstrapMd,
    heartbeatMd: template.heartbeatMd,
  };
}

function deriveSlug(name: string): string {
  return name.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}

export function TemplateDrawer({
  mode,
  slug,
  onClose,
}: {
  mode: "view" | "create";
  slug?: string;
  onClose: () => void;
}) {
  const { template, isLoading } = useTemplate(mode === "view" ? (slug ?? "") : "");
  const createTemplate = useCreateTemplate();
  const updateTemplate = useUpdateTemplate();

  const [editing, setEditing] = useState(mode === "create");
  const [name, setName] = useState("");
  const [files, setFiles] = useState<TemplateFiles>(EMPTY_FILES);
  const [file, setFile] = useState<TemplateFileKey>("soulMd");
  const [saved, setSaved] = useState(false);

  // In view mode the fetched template is displayed directly; local draft state
  // only becomes meaningful once the user starts editing (snapshot below).
  const displayName = editing ? name : (template?.templateName ?? "");
  const displayFiles = editing ? files : template ? filesFrom(template) : EMPTY_FILES;

  const mutationError = createTemplate.error ?? updateTemplate.error;
  const pending = createTemplate.isPending || updateTemplate.isPending;

  function handleStartEdit() {
    if (template) {
      setName(template.templateName);
      setFiles(filesFrom(template));
    }
    setEditing(true);
  }

  async function handleSave() {
    createTemplate.reset();
    updateTemplate.reset();
    try {
      if (mode === "create") {
        await createTemplate.mutateAsync({ templateName: name, ...files });
        onClose();
        return;
      }
      // Saving publishes a new immutable version of the lineage.
      await updateTemplate.mutateAsync({ slug: slug!, templateName: name, ...files });
      setEditing(false);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch {
      // error displayed via mutationError
    }
  }

  function handleCancelEdit() {
    if (mode === "create") {
      onClose();
      return;
    }
    setEditing(false);
  }

  const headerSlug =
    mode === "create" ? deriveSlug(name) || "—" : `${slug}@v${template?.version ?? "…"}`;

  return (
    <div className="fixed inset-0 z-50">
      <div
        className="absolute inset-0"
        style={{ background: "rgba(20,16,10,.4)" }}
        onClick={onClose}
      />
      <aside
        className="absolute top-0 right-0 bottom-0 flex flex-col af-drawer-panel"
        style={{ width: "min(36.25rem, 95vw)", background: "var(--bg)", boxShadow: "var(--shadow-pop)" }}
      >
        <header
          className="px-6 pt-5 pb-3.5 flex items-start justify-between"
          style={{ borderBottom: "1px solid var(--line)" }}
        >
          <div>
            <div
              className="text-xs uppercase tracking-[0.08em] font-semibold mb-1"
              style={{ color: "var(--ink-3)" }}
            >
              {mode === "create" ? "New template" : "Template"} ·{" "}
              <span className="font-mono normal-case">{headerSlug}</span>
            </div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-semibold tracking-tight m-0" style={{ color: "var(--ink)" }}>
                {mode === "create" ? (name || "Untitled template") : template?.templateName ?? "…"}
              </h2>
              {template && <TemplateSourceBadge source={template.templateSource} />}
            </div>
          </div>
          <button className="af-btn af-btn-ghost af-btn-icon" onClick={onClose} aria-label="Close">
            <XIcon />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-6 py-5 flex flex-col gap-4">
          {mode === "view" && isLoading && (
            <div className="text-[13px]" style={{ color: "var(--ink-3)" }}>Loading…</div>
          )}

          {(mode === "create" || template) && (
            <>
              <div className="flex flex-col gap-1.5">
                <label className="text-[13px] font-medium" style={{ color: "var(--ink-2)" }}>
                  Template name
                </label>
                {editing ? (
                  <input
                    className="af-input"
                    aria-label="Template name"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="My Template"
                  />
                ) : (
                  <div className="text-[14px]" style={{ color: "var(--ink)" }}>{displayName}</div>
                )}
                {mode === "create" && (
                  <div className="text-[12px]" style={{ color: "var(--ink-4)" }}>
                    Slug: <span className="font-mono">{deriveSlug(name) || "—"}</span> (derived from the name, fixed after creation)
                  </div>
                )}
              </div>

              {mode === "view" && template && (
                <div className="text-[12.5px]" style={{ color: "var(--ink-3)" }}>
                  Version <span className="font-mono">v{template.version}</span>
                  {" — saving an edit publishes a new version. "}
                  <span className="font-mono">{"{{ … }}"}</span> placeholders are rendered when an agent starts.
                </div>
              )}

              <div className="flex flex-wrap gap-1">
                {TEMPLATE_FILE_KEYS.map((k) => (
                  <button
                    key={k}
                    type="button"
                    className="af-btn af-btn-sm"
                    style={{
                      background: file === k ? "var(--ink)" : undefined,
                      color: file === k ? "var(--bg)" : undefined,
                    }}
                    onClick={() => setFile(k)}
                  >
                    {templateFileLabel(k)}
                  </button>
                ))}
              </div>

              <textarea
                className="af-input font-mono text-[0.781rem] leading-[1.65] resize-none flex-1"
                rows={18}
                readOnly={!editing}
                aria-label={`${templateFileLabel(file)} content`}
                value={displayFiles[file]}
                onChange={(e) => setFiles((prev) => ({ ...prev, [file]: e.target.value }))}
              />

              {mutationError && (
                <div className="text-[13px]" style={{ color: "var(--err)" }}>
                  {mutationError.message}
                </div>
              )}
            </>
          )}
        </div>

        <footer
          className="px-6 py-4 flex items-center justify-end gap-2 flex-shrink-0"
          style={{ borderTop: "1px solid var(--line)" }}
        >
          {editing ? (
            <>
              <button className="af-btn af-btn-ghost" onClick={handleCancelEdit}>Cancel</button>
              <button
                className="af-btn af-btn-primary"
                disabled={pending || !name.trim()}
                onClick={() => void handleSave()}
              >
                {pending ? "Saving…" : mode === "create" ? "Create template" : "Save"}
              </button>
            </>
          ) : (
            <>
              {saved && (
                <span className="text-[13px] mr-auto" style={{ color: "var(--ok)" }}>
                  Saved as v{template?.version}
                </span>
              )}
              <button
                className="af-btn af-btn-primary"
                disabled={!template}
                onClick={handleStartEdit}
              >
                Edit template
              </button>
            </>
          )}
        </footer>
      </aside>
    </div>
  );
}
