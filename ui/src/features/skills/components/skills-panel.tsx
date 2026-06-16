"use client";

import { useState, useRef } from "react";

import { AppErrorState } from "@/components/app-error-state";
import { PlusIcon, ShieldIcon } from "@/components/icons";

import { type Skill } from "../schemas";
import {
  useCreateSkill,
  useUpdateSkill,
  useDeleteSkill,
  type SkillCreatePayload,
  type SkillUpdatePayload,
} from "../hooks/use-skill-mutations";
import { useSkills } from "../hooks/use-skills";
import { ALL_PROVIDERS, SKILL_PROVIDER_LABELS, fileToBase64 } from "../utils";

function Hint({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="flex items-start gap-2 text-[13px] rounded-xl px-3.5 py-3 mb-5 leading-[1.5]"
      style={{ background: "var(--bg-soft)", color: "var(--ink-3)" }}
    >
      {children}
    </div>
  );
}

function SkillRow({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="flex items-center gap-3 px-0 py-3.5"
      style={{ borderBottom: "1px solid var(--line)" }}
    >
      {children}
    </div>
  );
}

function ProviderBadge({ provider }: { provider: string }) {
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium"
      style={{ background: "var(--bg-soft)", color: "var(--ink-3)", border: "1px solid var(--line)" }}
    >
      {SKILL_PROVIDER_LABELS[provider] ?? provider}
    </span>
  );
}

function SectionHeader({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="text-xs font-semibold uppercase tracking-[0.07em] pt-4 pb-1"
      style={{ color: "var(--ink-4)" }}
    >
      {children}
    </div>
  );
}

type DialogMode = { kind: "create" } | { kind: "edit"; skill: Skill };

interface SkillDialogProps {
  mode: DialogMode;
  onClose: () => void;
}

function SkillDialog({ mode, onClose }: SkillDialogProps) {
  const isEdit = mode.kind === "edit";
  const existing = isEdit ? mode.skill : null;

  const [name, setName] = useState(existing?.name ?? "");
  const [toolsPointer, setToolsPointer] = useState(existing?.toolsPointer ?? "");
  const [selectedProviders, setSelectedProviders] = useState<string[]>(
    existing?.requiredProviders ?? [],
  );
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const createSkill = useCreateSkill();
  const updateSkill = useUpdateSkill();

  const isPending = createSkill.isPending || updateSkill.isPending;
  const mutationError = createSkill.error ?? updateSkill.error;

  function toggleProvider(value: string) {
    setSelectedProviders((prev) =>
      prev.includes(value) ? prev.filter((p) => p !== value) : [...prev, value],
    );
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFileError(null);

    if (!isEdit && !file) {
      setFileError("A zip file is required.");
      return;
    }

    try {
      if (isEdit) {
        const payload: SkillUpdatePayload = {
          skillId: existing!.id,
          name: name.trim() || undefined,
          toolsPointer: toolsPointer.trim() || null,
          requiredProviders: selectedProviders,
        };
        if (file) {
          payload.zipContent = await fileToBase64(file);
        }
        await updateSkill.mutateAsync(payload);
      } else {
        const zipContent = await fileToBase64(file!);
        const payload: SkillCreatePayload = {
          name: name.trim(),
          zipContent,
          toolsPointer: toolsPointer.trim() || null,
          requiredProviders: selectedProviders,
        };
        await createSkill.mutateAsync(payload);
      }
      onClose();
    } catch {
      // error displayed via mutationError
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div
        className="absolute inset-0"
        style={{ background: "rgba(20,16,10,.45)" }}
        onClick={onClose}
      />
      <div
        className="relative w-full max-w-md rounded-2xl p-6 shadow-2xl"
        style={{ background: "var(--bg-elev)", border: "1px solid var(--line)" }}
      >
        <h3 className="text-[1.0625rem] font-semibold tracking-tight mb-5" style={{ color: "var(--ink)" }}>
          {isEdit ? "Edit skill" : "New skill"}
        </h3>

        <form onSubmit={(e) => { void handleSubmit(e); }} className="flex flex-col gap-4">
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
              Skill zip {!isEdit && <span style={{ color: "var(--err)" }}>*</span>}
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
            {isEdit && (
              <span className="text-xs" style={{ color: "var(--ink-4)" }}>
                Leave empty to keep the existing zip.
              </span>
            )}
            {fileError && (
              <span className="text-xs" style={{ color: "var(--err)" }}>{fileError}</span>
            )}
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="font-medium text-[0.844rem]" style={{ color: "var(--ink)" }}>
              Tools pointer <span className="font-normal" style={{ color: "var(--ink-4)" }}>(optional)</span>
            </label>
            <input
              className="af-input font-mono text-[0.8125rem]"
              value={toolsPointer}
              onChange={(e) => setToolsPointer(e.target.value)}
              placeholder="e.g. path/to/tools.md"
            />
          </div>

          <div className="flex flex-col gap-2">
            <label className="font-medium text-[0.844rem]" style={{ color: "var(--ink)" }}>
              Required providers <span className="font-normal" style={{ color: "var(--ink-4)" }}>(optional)</span>
            </label>
            <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
              {ALL_PROVIDERS.map(({ value, label }) => (
                <label
                  key={value}
                  className="flex items-center gap-2 text-[0.844rem] cursor-pointer"
                  style={{ color: "var(--ink-2)" }}
                >
                  <input
                    type="checkbox"
                    checked={selectedProviders.includes(value)}
                    onChange={() => toggleProvider(value)}
                    className="rounded"
                  />
                  {label}
                </label>
              ))}
            </div>
          </div>

          {mutationError && (
            <div className="text-[0.8125rem]" style={{ color: "var(--err)" }}>
              {mutationError.message}
            </div>
          )}

          <div className="flex gap-2 justify-end pt-1">
            <button type="button" className="af-btn af-btn-ghost" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="af-btn af-btn-primary" disabled={isPending}>
              {isPending ? "Saving…" : isEdit ? "Save changes" : "Create skill"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

interface DeleteConfirmRowProps {
  skill: Skill;
  onCancel: () => void;
  onError: (message: string) => void;
}

function DeleteConfirmRow({ skill, onCancel, onError }: DeleteConfirmRowProps) {
  const deleteSkill = useDeleteSkill();

  return (
    <SkillRow>
      <div className="flex-1 text-[0.844rem]" style={{ color: "var(--ink-3)" }}>
        Delete <span className="font-medium" style={{ color: "var(--ink)" }}>{skill.name}</span>? This cannot be undone.
      </div>
      <button
        className="af-btn af-btn-sm af-btn-ghost"
        disabled={deleteSkill.isPending}
        onClick={onCancel}
      >
        Cancel
      </button>
      <button
        className="af-btn af-btn-sm"
        disabled={deleteSkill.isPending}
        style={{ borderColor: "var(--err)", color: "var(--err)" }}
        onClick={() => {
          void deleteSkill.mutateAsync(skill.id).then(onCancel).catch((err: Error) => {
            onError(err.message);
            onCancel();
          });
        }}
      >
        {deleteSkill.isPending ? "Deleting…" : "Delete"}
      </button>
    </SkillRow>
  );
}

export function SkillsPanel() {
  const { skills, isLoading, error, refetch } = useSkills();
  const [dialog, setDialog] = useState<DialogMode | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<{ skillId: string; message: string } | null>(null);

  const platformSkills = skills.filter((s) => s.source === "aai_cli");
  const customSkills = skills.filter((s) => s.source === "custom");

  if (isLoading) {
    return (
      <div className="flex flex-col gap-3 animate-pulse">
        {Array.from({ length: 4 }).map((_, i) => (
          <div
            key={i}
            className="h-11 rounded-xl"
            style={{ background: "var(--bg-soft)" }}
          />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <AppErrorState
        error={error}
        title="We couldn't load skills"
        description="The skills list is unavailable right now."
        onRetry={() => { void refetch(); }}
        retryLabel="Retry"
      />
    );
  }

  return (
    <>
      <Hint>
        <ShieldIcon style={{ flexShrink: 0, marginTop: 1 }} />
        Platform skills are provided by AAI Labs and cannot be modified. Custom skills are uploaded by your organization and can be assigned to agents.
      </Hint>

      <div className="mb-4">
        <button
          className="af-btn af-btn-primary"
          onClick={() => setDialog({ kind: "create" })}
        >
          <PlusIcon /> New skill
        </button>
      </div>

      {platformSkills.length > 0 && (
        <div>
          <SectionHeader>Platform</SectionHeader>
          {platformSkills.map((skill) => (
            <SkillRow key={skill.id}>
              <div className="flex-1 min-w-0">
                <div className="font-medium text-[14px]" style={{ color: "var(--ink)" }}>
                  {skill.name}
                </div>
                {skill.requiredProviders.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-1">
                    {skill.requiredProviders.map((p) => (
                      <ProviderBadge key={p} provider={p} />
                    ))}
                  </div>
                )}
              </div>
              <span
                className="text-[11px] font-medium px-2 py-0.5 rounded-md flex-shrink-0"
                style={{ background: "var(--bg-soft)", color: "var(--ink-4)" }}
              >
                Platform
              </span>
            </SkillRow>
          ))}
        </div>
      )}

      {customSkills.length > 0 && (
        <div>
          <SectionHeader>Custom</SectionHeader>
          {customSkills.map((skill) =>
            deletingId === skill.id ? (
              <DeleteConfirmRow
                key={skill.id}
                skill={skill}
                onCancel={() => setDeletingId(null)}
                onError={(message) => setDeleteError({ skillId: skill.id, message })}
              />
            ) : (
              <SkillRow key={skill.id}>
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-[14px]" style={{ color: "var(--ink)" }}>
                    {skill.name}
                  </div>
                  {deleteError?.skillId === skill.id && (
                    <div className="text-[0.75rem] mt-0.5" style={{ color: "var(--err)" }}>
                      {deleteError.message}
                    </div>
                  )}
                  {skill.requiredProviders.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-1">
                      {skill.requiredProviders.map((p) => (
                        <ProviderBadge key={p} provider={p} />
                      ))}
                    </div>
                  )}
                </div>
                <button
                  className="af-btn af-btn-sm af-btn-ghost"
                  onClick={() => setDialog({ kind: "edit", skill })}
                >
                  Edit
                </button>
                <button
                  className="af-btn af-btn-sm af-btn-ghost"
                  style={{ color: "var(--err)" }}
                  onClick={() => { setDeleteError(null); setDeletingId(skill.id); }}
                >
                  Delete
                </button>
              </SkillRow>
            ),
          )}
        </div>
      )}

      {skills.length === 0 && (
        <div
          className="flex flex-col items-center justify-center text-center py-10 rounded-2xl"
          style={{ border: "1px dashed var(--line-strong)", color: "var(--ink-3)" }}
        >
          <div className="font-medium text-[0.9375rem] mb-1" style={{ color: "var(--ink)" }}>
            No skills yet
          </div>
          <div className="text-[0.844rem]">
            Create your first custom skill to get started.
          </div>
        </div>
      )}

      {dialog && (
        <SkillDialog mode={dialog} onClose={() => setDialog(null)} />
      )}
    </>
  );
}