"use client";

import { useRef, useState } from "react";

import { XIcon } from "@/components/icons";

import {
  type SkillCreatePayload,
  type SkillUpdatePayload,
  useCreateSkill,
  useDeleteSkill,
  useUpdateSkill,
} from "../hooks/use-skill-mutations";
import type { Skill } from "../schemas";
import { ALL_PROVIDERS, SKILL_PROVIDER_LABELS, fileToBase64 } from "../utils";

type DrawerMode =
  | { kind: "create" }
  | { kind: "view"; skill: Skill };

interface SkillDrawerProps {
  mode: DrawerMode;
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

export function SkillDrawer({ mode, onClose }: SkillDrawerProps) {
  const isCreate = mode.kind === "create";
  const skill = mode.kind === "view" ? mode.skill : null;
  const isCustom = skill?.source === "custom";

  const [editing, setEditing] = useState(isCreate);
  const [confirming, setConfirming] = useState(false);

  const [name, setName] = useState(skill?.name ?? "");
  const [selectedProviders, setSelectedProviders] = useState<string[]>(
    skill?.requiredProviders ?? [],
  );
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const createSkill = useCreateSkill();
  const updateSkill = useUpdateSkill();
  const deleteSkill = useDeleteSkill();

  const isPending = createSkill.isPending || updateSkill.isPending;
  const mutationError = createSkill.error ?? updateSkill.error;

  function toggleProvider(value: string) {
    setSelectedProviders((prev) =>
      prev.includes(value) ? prev.filter((p) => p !== value) : [...prev, value],
    );
  }

  function handleStartEdit() {
    setEditing(true);
  }

  function handleCancelEdit() {
    setEditing(false);
    setFileError(null);
    setFile(null);
    if (fileRef.current) fileRef.current.value = "";
    // Reset form back to current skill values
    setName(skill?.name ?? "");
    setSelectedProviders(skill?.requiredProviders ?? []);
  }

  async function handleSave() {
    setFileError(null);

    if (isCreate && !file) {
      setFileError("A zip file is required.");
      return;
    }

    try {
      if (skill) {
        const payload: SkillUpdatePayload = {
          skillId: skill.id,
          name: name.trim() || undefined,
          requiredProviders: selectedProviders,
        };
        if (file) {
          payload.zipContent = await fileToBase64(file);
        }
        await updateSkill.mutateAsync(payload);
        setEditing(false);
      } else {
        const zipContent = await fileToBase64(file!);
        const payload: SkillCreatePayload = {
          name: name.trim(),
          zipContent,
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
                  Skill zip {isCreate && <span style={{ color: "var(--err)" }}>*</span>}
                </label>
                <input
                  ref={fileRef}
                  type="file"
                  accept=".zip"
                  className="af-input text-[0.8125rem]"
                  onChange={(e) => {
                    setFile(e.target.files?.[0] ?? null);
                    setFileError(null);
                  }}
                />
                {skill && (
                  <span className="text-xs" style={{ color: "var(--ink-4)" }}>
                    Leave empty to keep the existing zip.
                  </span>
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
            </div>
          )}
        </div>

        <footer
          className="px-6 py-4 flex items-center gap-2 flex-shrink-0"
          style={{ borderTop: "1px solid var(--line)" }}
        >
          {editing ? (
            <>
              <button
                type="button"
                className="af-btn af-btn-ghost"
                onClick={isCreate ? onClose : handleCancelEdit}
              >
                Cancel
              </button>
              <button
                type="button"
                className="af-btn af-btn-primary ml-auto"
                disabled={isPending}
                onClick={() => { void handleSave(); }}
              >
                {isPending ? "Saving…" : isCreate ? "Create skill" : "Save changes"}
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
          ) : isCustom ? (
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
                onClick={handleStartEdit}
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