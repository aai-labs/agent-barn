"use client";

import { useState } from "react";

import { XIcon } from "@/components/icons";

import { useSkillFiles } from "../hooks/use-skill-files";
import { SkillFilesEditor } from "./skill-files-editor";
import {
  type SkillCreatePayload,
  type SkillFilePayload,
  type SkillUpdatePayload,
  useCreateSkill,
  useDeleteSkill,
  useDiscardSkillDraft,
  usePublishSkillDraft,
  useStartSkillDraft,
  useUpdateSkill,
  useUpdateSkillDraft,
} from "../hooks/use-skill-mutations";
import type { Skill } from "../schemas";
import { ALL_PROVIDERS, DEFAULT_ENTRY_PATH, NEW_SKILL_TEMPLATE, SKILL_PROVIDER_LABELS } from "../utils";

type DrawerMode =
  | { kind: "create" }
  | { kind: "view"; skill: Skill };

interface SkillDrawerProps {
  mode: DrawerMode;
  canManage: boolean;
  onClose: () => void;
}

export function SkillSourceBadge({ source }: { source: string }) {
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium"
      style={{
        background: "var(--bg-soft)",
        color: "var(--ink-3)",
        border: "1px solid var(--line)",
      }}
    >
      {source === "aai_cli" ? "Platform" : "Custom"}
    </span>
  );
}

export function SkillDrawer({ mode, canManage, onClose }: SkillDrawerProps) {
  const isCreate = mode.kind === "create";
  const skill = mode.kind === "view" ? mode.skill : null;
  const isCustom = skill?.source === "custom";

  const [editing, setEditing] = useState(isCreate && canManage);
  const [confirming, setConfirming] = useState(false);

  const [name, setName] = useState(skill?.name ?? "");
  const [description, setDescription] = useState(skill?.description ?? "");
  const [selectedProviders, setSelectedProviders] = useState<string[]>(
    skill?.requiredProviders ?? [],
  );
  // Local edits to the draft's files, held separately from the fetched draft so a
  // background refetch cannot clobber what the user typed. Populated once the draft
  // is started/loaded; null means "no draft loaded into the editor yet".
  const [localFiles, setLocalFiles] = useState<SkillFilePayload[] | null>(
    isCreate ? [{ path: DEFAULT_ENTRY_PATH, content: NEW_SKILL_TEMPLATE }] : null,
  );
  const [fileError, setFileError] = useState<string | null>(null);

  const entryPath = skill?.entryPath ?? DEFAULT_ENTRY_PATH;
  const { files: publishedFiles, isLoading: filesLoading } = useSkillFiles(skill?.id ?? null);

  const files = editing
    ? (localFiles ?? [])
    : publishedFiles.map((f) => ({ path: f.path, content: f.content }));

  const createSkill = useCreateSkill();
  const updateSkill = useUpdateSkill();
  const deleteSkill = useDeleteSkill();
  const startDraft = useStartSkillDraft();
  const updateDraft = useUpdateSkillDraft();
  const discardDraft = useDiscardSkillDraft();
  const publishDraft = usePublishSkillDraft();

  const isSavingMetadata = createSkill.isPending || updateSkill.isPending;
  const isPending = isSavingMetadata || startDraft.isPending || updateDraft.isPending || publishDraft.isPending;
  const mutationError =
    createSkill.error ?? updateSkill.error ?? startDraft.error ?? updateDraft.error ?? publishDraft.error;

  function handleFilesChange(next: SkillFilePayload[]) {
    setLocalFiles(next);
    setFileError(null);
  }

  function toggleProvider(value: string) {
    setSelectedProviders((prev) =>
      prev.includes(value) ? prev.filter((p) => p !== value) : [...prev, value],
    );
  }

  async function handleStartEdit() {
    if (!canManage) return;
    if (skill) {
      try {
        const draft = await startDraft.mutateAsync({ skillId: skill.id });
        setLocalFiles(draft.files);
      } catch {
        return;
      }
    }
    setEditing(true);
  }

  function resetToPublished() {
    setFileError(null);
    setName(skill?.name ?? "");
    setDescription(skill?.description ?? "");
    setSelectedProviders(skill?.requiredProviders ?? []);
    setLocalFiles(null);
  }

  async function handleDiscardDraft() {
    if (skill) {
      try {
        await discardDraft.mutateAsync(skill.id);
      } catch {
        return;
      }
    }
    resetToPublished();
    setEditing(false);
  }

  async function handleSaveDraft() {
    if (!skill) return;
    setFileError(null);
    if (!files.some((f) => f.path === entryPath)) {
      setFileError(`A skill must include its entry point, ${entryPath}.`);
      return;
    }
    try {
      const metadataPayload: SkillUpdatePayload = {
        skillId: skill.id,
        name: name.trim() || undefined,
        description: description.trim() || undefined,
        requiredProviders: selectedProviders,
      };
      const [, draft] = await Promise.all([
        updateSkill.mutateAsync(metadataPayload),
        updateDraft.mutateAsync({ skillId: skill.id, files }),
      ]);
      setLocalFiles(draft.files);
    } catch {
      // error displayed via mutationError
    }
  }

  async function handlePublish() {
    setFileError(null);

    if (!files.some((f) => f.path === entryPath)) {
      setFileError(`A skill must include its entry point, ${entryPath}.`);
      return;
    }

    try {
      if (skill) {
        const metadataPayload: SkillUpdatePayload = {
          skillId: skill.id,
          name: name.trim() || undefined,
          description: description.trim() || undefined,
          requiredProviders: selectedProviders,
        };
        await Promise.all([
          updateSkill.mutateAsync(metadataPayload),
          updateDraft.mutateAsync({ skillId: skill.id, files }),
        ]);
        await publishDraft.mutateAsync(skill.id);
        setLocalFiles(null);
        setEditing(false);
      } else {
        const payload: SkillCreatePayload = {
          name: name.trim(),
          description: description.trim() || undefined,
          files,
          requiredProviders: selectedProviders,
        };
        await createSkill.mutateAsync(payload);
        onClose();
      }
    } catch {
      // error displayed via mutationError
    }
  }

  async function handleDelete() {
    try {
      await deleteSkill.mutateAsync(skill!.id);
      onClose();
    } catch {
      // error displayed via deleteSkill.error
    }
  }

  const subLabel = isCreate ? "New skill" : editing ? "Edit skill" : "Skill";
  const heading = isCreate ? "New skill" : (skill?.name ?? "…");

  return (
    <div className="fixed inset-0 z-50">
      <div
        className="absolute inset-0"
        style={{ background: "rgba(20,16,10,.4)" }}
        onClick={onClose}
      />
      <aside
        className="absolute top-0 right-0 bottom-0 flex flex-col af-drawer-panel"
        style={{
          width: "min(36.25rem, 95vw)",
          background: "var(--bg)",
          boxShadow: "var(--shadow-pop)",
        }}
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
              {subLabel}
            </div>
            <div className="flex items-center gap-2">
              <h2
                className="text-lg font-semibold tracking-tight m-0"
                style={{ color: "var(--ink)" }}
              >
                {heading}
              </h2>
              {skill && <SkillSourceBadge source={skill.source} />}
            </div>
          </div>
          <button
            className="af-btn af-btn-ghost af-btn-icon"
            onClick={onClose}
            aria-label="Close drawer"
          >
            <XIcon />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-6 py-5">
          {editing ? (
            <div className="flex flex-col gap-4">
              {skill && (
                <div
                  className="text-[0.8125rem] rounded-xl px-3.5 py-3 leading-[1.5]"
                  style={{ background: "var(--bg-soft)", color: "var(--ink-3)" }}
                >
                  Agents currently using this skill will keep running the old version until they
                  are restarted.
                </div>
              )}

              <div className="flex flex-col gap-1.5">
                <label className="font-medium text-[0.844rem]" style={{ color: "var(--ink)" }}>
                  Name <span style={{ color: "var(--err)" }}>*</span>
                </label>
                <input
                  className="af-input"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                  maxLength={255}
                  placeholder="e.g. my-tool"
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <label className="font-medium text-[0.844rem]" style={{ color: "var(--ink)" }}>
                  Description{" "}
                  <span className="font-normal" style={{ color: "var(--ink-4)" }}>
                    (optional)
                  </span>
                </label>
                <input
                  className="af-input"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  maxLength={2000}
                  placeholder="What this skill helps the agent do"
                />
                <span className="text-xs" style={{ color: "var(--ink-4)" }}>
                  Shown to the agent alongside the pointer to this skill.
                </span>
              </div>

              <div className="flex flex-col gap-1.5">
                <label className="font-medium text-[0.844rem]" style={{ color: "var(--ink)" }}>
                  Files <span style={{ color: "var(--err)" }}>*</span>
                </label>
                {filesLoading && !isCreate ? (
                  <span className="text-[13px]" style={{ color: "var(--ink-4)" }}>
                    Loading files…
                  </span>
                ) : (
                  <SkillFilesEditor
                    files={files}
                    onChange={handleFilesChange}
                    entryPath={entryPath}
                  />
                )}
                {fileError && (
                  <span className="text-xs" style={{ color: "var(--err)" }}>
                    {fileError}
                  </span>
                )}
              </div>

              <div className="flex flex-col gap-2">
                <label className="font-medium text-[0.844rem]" style={{ color: "var(--ink)" }}>
                  Required providers{" "}
                  <span className="font-normal" style={{ color: "var(--ink-4)" }}>
                    (optional)
                  </span>
                </label>
                <div className="flex flex-wrap gap-1.5">
                  {ALL_PROVIDERS.map(({ value, label }) => {
                    const selected = selectedProviders.includes(value);
                    return (
                      <button
                        key={value}
                        type="button"
                        onClick={() => toggleProvider(value)}
                        className="inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium transition-colors"
                        style={
                          selected
                            ? { background: "var(--ink)", color: "var(--bg)", border: "1px solid var(--ink)" }
                            : { background: "var(--bg-soft)", color: "var(--ink-3)", border: "1px solid var(--line)" }
                        }
                      >
                        {label}
                      </button>
                    );
                  })}
                </div>
              </div>

              {mutationError && (
                <div className="text-[0.8125rem]" style={{ color: "var(--err)" }}>
                  {mutationError.message}
                </div>
              )}
            </div>
          ) : (
            <div className="flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <div className="text-[13px] font-medium" style={{ color: "var(--ink-2)" }}>
                  Name
                </div>
                <div className="text-[14px]" style={{ color: "var(--ink)" }}>
                  {skill?.name}
                </div>
              </div>
              {skill?.description && (
                <div className="flex flex-col gap-1.5">
                  <div className="text-[13px] font-medium" style={{ color: "var(--ink-2)" }}>
                    Description
                  </div>
                  <div className="text-[14px]" style={{ color: "var(--ink)" }}>
                    {skill.description}
                  </div>
                </div>
              )}
              <div className="flex flex-col gap-1.5">
                <div className="text-[13px] font-medium" style={{ color: "var(--ink-2)" }}>
                  Required providers
                </div>
                {(skill?.requiredProviders ?? []).length > 0 ? (
                  <div className="flex flex-wrap gap-1.5">
                    {skill!.requiredProviders.map((p) => (
                      <span
                        key={p}
                        className="inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium"
                        style={{
                          background: "var(--bg-soft)",
                          color: "var(--ink-3)",
                          border: "1px solid var(--line)",
                        }}
                      >
                        {SKILL_PROVIDER_LABELS[p] ?? p}
                      </span>
                    ))}
                  </div>
                ) : (
                  <div className="text-[13px]" style={{ color: "var(--ink-4)" }}>
                    None
                  </div>
                )}
              </div>
              <div className="flex flex-col gap-1.5">
                <div className="flex items-center justify-between">
                  <div className="text-[13px] font-medium" style={{ color: "var(--ink-2)" }}>
                    Files
                  </div>
                  <span className="text-[11px]" style={{ color: "var(--ink-4)" }}>
                    v{skill?.version} · ./skills/{skill?.rootDir}
                  </span>
                </div>
                {filesLoading ? (
                  <div className="text-[13px]" style={{ color: "var(--ink-4)" }}>
                    Loading files…
                  </div>
                ) : (
                  <SkillFilesEditor
                    files={files}
                    onChange={handleFilesChange}
                    entryPath={entryPath}
                    readOnly
                  />
                )}
              </div>
            </div>
          )}
        </div>

        <footer
          className="px-6 py-4 flex items-center gap-2 flex-shrink-0"
          style={{ borderTop: "1px solid var(--line)" }}
        >
          {editing && isCreate ? (
            <>
              <button type="button" className="af-btn af-btn-ghost" onClick={onClose}>
                Cancel
              </button>
              <button
                type="button"
                className="af-btn af-btn-primary ml-auto"
                disabled={isPending}
                onClick={() => { void handlePublish(); }}
              >
                {isPending ? "Creating…" : "Create skill"}
              </button>
            </>
          ) : editing ? (
            <>
              <button
                type="button"
                className="af-btn af-btn-ghost"
                style={{ color: "var(--err)" }}
                disabled={isPending}
                onClick={() => { void handleDiscardDraft(); }}
              >
                Discard
              </button>
              <button
                type="button"
                className="af-btn af-btn-ghost ml-auto"
                disabled={isPending}
                onClick={() => { void handleSaveDraft(); }}
              >
                {updateDraft.isPending || isSavingMetadata ? "Saving…" : "Save draft"}
              </button>
              <button
                type="button"
                className="af-btn af-btn-primary"
                disabled={isPending}
                onClick={() => { void handlePublish(); }}
              >
                {publishDraft.isPending ? "Publishing…" : "Publish"}
              </button>
            </>
          ) : confirming ? (
            <div className="flex flex-col gap-2 w-full">
              <div className="flex items-center gap-2">
                <span className="text-[13px] flex-1" style={{ color: "var(--ink-3)" }}>
                  Delete <strong style={{ color: "var(--ink)" }}>{skill?.name}</strong>? This
                  cannot be undone.
                </span>
                <button
                  type="button"
                  className="af-btn af-btn-ghost af-btn-sm"
                  disabled={deleteSkill.isPending}
                  onClick={() => { setConfirming(false); deleteSkill.reset(); }}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className="af-btn af-btn-sm"
                  style={{ borderColor: "var(--err)", color: "var(--err)" }}
                  disabled={deleteSkill.isPending}
                  onClick={() => { void handleDelete(); }}
                >
                  {deleteSkill.isPending ? "Deleting…" : "Delete"}
                </button>
              </div>
              {deleteSkill.error && (
                <div className="text-[0.8125rem]" style={{ color: "var(--err)" }}>
                  {deleteSkill.error.message}
                </div>
              )}
            </div>
          ) : isCustom && canManage ? (
            <>
              <button
                className="af-btn af-btn-ghost af-btn-sm"
                style={{ color: "var(--err)" }}
                onClick={() => setConfirming(true)}
              >
                Delete
              </button>
              <button
                className="af-btn af-btn-primary ml-auto"
                onClick={() => { void handleStartEdit(); }}
              >
                Edit skill
              </button>
            </>
          ) : (
            <button className="af-btn af-btn-ghost ml-auto" onClick={onClose}>
              Close
            </button>
          )}
        </footer>
      </aside>
    </div>
  );
}