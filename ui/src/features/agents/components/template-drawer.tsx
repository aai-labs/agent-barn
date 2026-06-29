"use client";

import { useState } from "react";
import { useDebouncedValue } from "@tanstack/react-pacer";
import { SearchIcon, XIcon } from "@/components/icons";
import { useSkills } from "@/features/skills/hooks/use-skills";
import { SkillSourceBadge } from "@/features/skills/components/skill-drawer";
import { SKILL_PROVIDER_LABELS } from "@/features/skills/utils";
import { useTemplateVersions } from "../hooks/use-template-versions";
import { useCreateTemplate } from "../hooks/use-create-template";
import { useUpdateTemplate } from "../hooks/use-update-template";
import type { AgentTemplateRead } from "../schemas";
import {
  TEMPLATE_FILE_KEYS,
  TemplateFileKey,
  TemplateSourceBadge,
  VersionSelect,
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

type SkillEntry = { id: string; name: string; source: string; requiredProviders: string[] };

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
  const { versions, isLoading, refetch } = useTemplateVersions(
    mode === "view" ? slug : null,
  );
  const createTemplate = useCreateTemplate();
  const updateTemplate = useUpdateTemplate();

  const [editing, setEditing] = useState(mode === "create");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [files, setFiles] = useState<TemplateFiles>(EMPTY_FILES);
  const [file, setFile] = useState<TemplateFileKey>("soulMd");
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const [savedVersion, setSavedVersion] = useState<number | null>(null);
  const [selectedSkillDetails, setSelectedSkillDetails] = useState<SkillEntry[]>([]);
  const [skillSearch, setSkillSearch] = useState("");
  const [debouncedSkillSearch] = useDebouncedValue(skillSearch, { wait: 300 });

  const { skills, isLoading: skillsLoading } = useSkills({ search: debouncedSkillSearch || undefined, pageSize: 100 });
  const requiredSkillIds = selectedSkillDetails.map((s) => s.id);
  const unselectedSkills = skills.filter((s) => !requiredSkillIds.includes(s.id));

  // The version currently being displayed/edited (defaults to latest).
  const resolvedVersion = selectedVersion ?? versions[0]?.version ?? null;
  const current = versions.find((v) => v.version === resolvedVersion) ?? versions[0];

  // In view mode the selected version is displayed directly; local draft state
  // only matters once the user starts editing (snapshotted from `current`).
  const displayName = mode === "create" ? name : (current?.templateName ?? "");
  const displayFiles = editing ? files : current ? filesFrom(current) : EMPTY_FILES;

  const mutationError = createTemplate.error ?? updateTemplate.error;
  const pending = createTemplate.isPending || updateTemplate.isPending;

  function handleStartEdit() {
    if (current) {
      setFiles(filesFrom(current));
      setDescription(current.description ?? "");
      setSelectedSkillDetails(
        current.requiredSkills.map((s) => ({
          id: s.id,
          name: s.name,
          source: s.source,
          requiredProviders: s.requiredProviders,
        })),
      );
    }
    setSkillSearch("");
    setSavedVersion(null);
    setEditing(true);
  }

  function addRequiredSkill(skill: SkillEntry) {
    setSelectedSkillDetails((prev) => [...prev, skill]);
  }

  function removeRequiredSkill(id: string) {
    setSelectedSkillDetails((prev) => prev.filter((s) => s.id !== id));
  }

  async function handleSave() {
    createTemplate.reset();
    updateTemplate.reset();
    try {
      if (mode === "create") {
        await createTemplate.mutateAsync({ templateName: name, description: description || null, ...files, requiredSkillIds });
        onClose();
        return;
      }
      // Saving publishes a new immutable version; the name is inherited.
      const updated = await updateTemplate.mutateAsync({ slug: slug!, description: description || null, ...files, requiredSkillIds });
      await refetch();
      setSelectedVersion(updated.version);
      setEditing(false);
      setSavedVersion(updated.version);
      setTimeout(() => setSavedVersion(null), 2500);
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
    mode === "create"
      ? deriveSlug(name) || "—"
      : `${slug}@v${current?.version ?? "…"}`;

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
                {mode === "create" ? (name || "Untitled template") : (current?.templateName ?? "…")}
              </h2>
              {current && <TemplateSourceBadge source={current.templateSource} />}
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

          {(mode === "create" || current) && (
            <>
              <div className="flex flex-col gap-1.5">
                <label className="text-[13px] font-medium" style={{ color: "var(--ink-2)" }}>
                  Template name
                </label>
                {mode === "create" ? (
                  <input
                    className="af-input"
                    aria-label="Template name"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="My Template"
                  />
                ) : (
                  // Names are immutable; new versions inherit the v1 name.
                  <div className="text-[14px]" style={{ color: "var(--ink)" }}>{displayName}</div>
                )}
                {mode === "create" && (
                  <div className="text-[12px]" style={{ color: "var(--ink-4)" }}>
                    Slug: <span className="font-mono">{deriveSlug(name) || "—"}</span> (derived from the name, fixed after creation)
                  </div>
                )}
              </div>

              <div className="flex flex-col gap-1.5">
                <label className="text-[13px] font-medium" style={{ color: "var(--ink-2)" }}>
                  Description
                </label>
                {editing ? (
                  <textarea
                    className="af-input font-mono text-[0.781rem] leading-[1.65] resize-none flex-1"
                    aria-label="Description"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="A short summary of what this template does…"
                    maxLength={500}
                    rows={4}
                  />
                ) : (
                  <div className="text-[13px] leading-[1.5]" style={{ color: current?.description ? "var(--ink-2)" : "var(--ink-4)" }}>
                    {current?.description || "No description."}
                  </div>
                )}
              </div>

              {mode === "view" && !editing && (
                <div className="flex items-center gap-3">
                  <label className="text-[13px] font-medium" style={{ color: "var(--ink-2)" }}>
                    Version
                  </label>
                  <div className="w-40">
                    <VersionSelect
                      versions={versions}
                      selectedVersion={resolvedVersion}
                      onChange={setSelectedVersion}
                    />
                  </div>
                </div>
              )}

              {mode === "view" && !editing && (
                <div className="flex flex-col gap-1.5">
                  <label className="text-[13px] font-medium" style={{ color: "var(--ink-2)" }}>
                    Required skills
                  </label>
                  {current && current.requiredSkills.length > 0 ? (
                    <div className="flex flex-wrap gap-1.5">
                      {current.requiredSkills.map((skill) => (
                        <span
                          key={skill.id}
                          className="text-[12px] font-medium px-2.5 py-0.5 rounded-full"
                          style={{ background: "var(--bg-soft)", color: "var(--ink-2)", border: "1px solid var(--line)" }}
                        >
                          {skill.name}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <div className="text-[13px]" style={{ color: "var(--ink-4)" }}>None</div>
                  )}
                </div>
              )}

              {mode === "view" && editing && (
                <div className="text-[12.5px]" style={{ color: "var(--ink-3)" }}>
                  Editing from <span className="font-mono">v{current?.version}</span>. Saving publishes a new
                  version. <span className="font-mono">{"{{ … }}"}</span> placeholders are rendered when an agent starts.
                </div>
              )}

              {editing && (
                <div className="flex flex-col gap-2">
                  <label className="text-[13px] font-medium" style={{ color: "var(--ink-2)" }}>
                    Required skills
                  </label>

                  {selectedSkillDetails.length > 0 ? (
                    <div className="flex flex-col gap-2 overflow-y-auto" style={{ maxHeight: "15rem" }}>
                      {selectedSkillDetails.map((skill) => (
                        <div
                          key={skill.id}
                          className="flex items-center gap-2 px-3.5 py-2.5 rounded-2xl flex-shrink-0"
                          style={{ border: "1px solid var(--line)", background: "var(--bg-soft)" }}
                        >
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                              <span className="font-medium text-[0.844rem]" style={{ color: "var(--ink)" }}>
                                {skill.name}
                              </span>
                              <SkillSourceBadge source={skill.source} />
                            </div>
                            {skill.requiredProviders.length > 0 && (
                              <span className="text-[0.75rem]" style={{ color: "var(--ink-4)" }}>
                                Requires:{" "}
                                {skill.requiredProviders.map((p) => SKILL_PROVIDER_LABELS[p] ?? p).join(", ")}
                              </span>
                            )}
                          </div>
                          <button
                            className="af-btn af-btn-sm af-btn-ghost"
                            onClick={() => removeRequiredSkill(skill.id)}
                          >
                            Remove
                          </button>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div
                      className="py-4 text-center rounded-2xl text-[0.8125rem]"
                      style={{ border: "1px dashed var(--line-strong)", color: "var(--ink-4)" }}
                    >
                      No required skills.
                    </div>
                  )}

                  <div
                    className="flex items-center gap-2 px-3 py-2 rounded-xl mt-1"
                    style={{ border: "1px solid var(--line)", background: "var(--bg-elev)" }}
                  >
                    <SearchIcon size={14} style={{ color: "var(--ink-4)", flexShrink: 0 }} />
                    <input
                      className="flex-1 text-[0.8125rem] outline-none bg-transparent"
                      style={{ color: "var(--ink)" }}
                      placeholder="Search skills to add…"
                      value={skillSearch}
                      onChange={(e) => setSkillSearch(e.target.value)}
                    />
                  </div>

                  <div className="flex flex-col gap-2 overflow-y-auto" style={{ maxHeight: "14rem" }}>
                    {skillsLoading && (
                      <div className="text-[0.8125rem] py-2 text-center" style={{ color: "var(--ink-3)" }}>
                        Loading…
                      </div>
                    )}
                    {!skillsLoading && unselectedSkills.length === 0 ? (
                      <div className="text-[0.8125rem] py-2 text-center" style={{ color: "var(--ink-3)" }}>
                        {skillSearch ? "No skills match." : "No more skills to add."}
                      </div>
                    ) : (
                      unselectedSkills.map((skill) => (
                        <div
                          key={skill.id}
                          className="flex items-center gap-2 px-3.5 py-2.5 rounded-2xl flex-shrink-0"
                          style={{ border: "1px solid var(--line)" }}
                        >
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                              <span className="font-medium text-[0.844rem]" style={{ color: "var(--ink)" }}>
                                {skill.name}
                              </span>
                              <SkillSourceBadge source={skill.source} />
                            </div>
                            {skill.requiredProviders.length > 0 && (
                              <span className="text-[0.75rem]" style={{ color: "var(--ink-4)" }}>
                                Requires:{" "}
                                {skill.requiredProviders.map((p) => SKILL_PROVIDER_LABELS[p] ?? p).join(", ")}
                              </span>
                            )}
                          </div>
                          <button
                            className="af-btn af-btn-sm af-btn-ghost"
                            onClick={() => addRequiredSkill({ id: skill.id, name: skill.name, source: skill.source, requiredProviders: skill.requiredProviders })}
                          >
                            Add
                          </button>
                        </div>
                      ))
                    )}
                  </div>
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
                className="af-input font-mono text-[0.781rem] leading-[1.65] resize-none"
                style={{ minHeight: "40rem" }}
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
                disabled={pending || (mode === "create" && !name.trim())}
                onClick={() => void handleSave()}
              >
                {pending ? "Saving…" : mode === "create" ? "Create template" : "Save"}
              </button>
            </>
          ) : (
            <>
              {savedVersion != null && (
                <span className="text-[13px] mr-auto" style={{ color: "var(--ok)" }}>
                  Saved as v{savedVersion}
                </span>
              )}
              <button
                className="af-btn af-btn-primary"
                disabled={!current}
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
