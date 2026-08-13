"use client";

import { useState } from "react";

import { XIcon } from "@/components/icons";

import { SkillFilesEditor } from "./skill-files-editor";
import {
  type SkillCreatePayload,
  type SkillFilePayload,
  useCreateSkill,
} from "../hooks/use-skill-mutations";
import { ALL_PROVIDERS, DEFAULT_ENTRY_PATH, NEW_SKILL_TEMPLATE } from "../utils";

interface SkillCreateDrawerProps {
  onClose: () => void;
  onCreated: (skillId: string) => void;
}

export function SkillCreateDrawer({ onClose, onCreated }: SkillCreateDrawerProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [selectedProviders, setSelectedProviders] = useState<string[]>([]);
  const [files, setFiles] = useState<SkillFilePayload[]>([
    { path: DEFAULT_ENTRY_PATH, content: NEW_SKILL_TEMPLATE },
  ]);
  const [fileError, setFileError] = useState<string | null>(null);

  const createSkill = useCreateSkill();

  function toggleProvider(value: string) {
    setSelectedProviders((prev) =>
      prev.includes(value) ? prev.filter((p) => p !== value) : [...prev, value],
    );
  }

  async function handleCreate() {
    setFileError(null);
    if (!files.some((f) => f.path === DEFAULT_ENTRY_PATH)) {
      setFileError(`A skill must include its entry point, ${DEFAULT_ENTRY_PATH}.`);
      return;
    }
    try {
      const payload: SkillCreatePayload = {
        name: name.trim(),
        description: description.trim() || undefined,
        files,
        requiredProviders: selectedProviders,
      };
      const created = await createSkill.mutateAsync(payload);
      onCreated(created.id);
    } catch {
      // error displayed via createSkill.error
    }
  }

  return (
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0" style={{ background: "rgba(20,16,10,.4)" }} onClick={onClose} />
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
              New skill
            </div>
            <h2 className="text-lg font-semibold tracking-tight m-0" style={{ color: "var(--ink)" }}>
              New skill
            </h2>
          </div>
          <button className="af-btn af-btn-ghost af-btn-icon" onClick={onClose} aria-label="Close drawer">
            <XIcon />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-6 py-5">
          <div className="flex flex-col gap-4">
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
              <SkillFilesEditor files={files} onChange={setFiles} entryPath={DEFAULT_ENTRY_PATH} />
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

            {createSkill.error && (
              <div className="text-[0.8125rem]" style={{ color: "var(--err)" }}>
                {createSkill.error.message}
              </div>
            )}
          </div>
        </div>

        <footer
          className="px-6 py-4 flex items-center gap-2 flex-shrink-0"
          style={{ borderTop: "1px solid var(--line)" }}
        >
          <button type="button" className="af-btn af-btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="af-btn af-btn-primary ml-auto"
            disabled={createSkill.isPending}
            onClick={() => { void handleCreate(); }}
          >
            {createSkill.isPending ? "Creating…" : "Create skill"}
          </button>
        </footer>
      </aside>
    </div>
  );
}
