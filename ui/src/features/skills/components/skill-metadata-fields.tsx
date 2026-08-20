"use client";

import { ALL_PROVIDERS } from "../utils";

interface SkillMetadataFieldsProps {
  name: string;
  onNameChange: (value: string) => void;
  namePlaceholder?: string;
  nameRequired?: boolean;
  description: string;
  onDescriptionChange: (value: string) => void;
  showDescriptionHint?: boolean;
  selectedProviders: string[];
  onToggleProvider: (value: string) => void;
}

/** Name / description / required-providers form, shared between creating a new
 * skill and editing a draft — both are just "the fields for a not-yet-published
 * skill version". */
export function SkillMetadataFields({
  name,
  onNameChange,
  namePlaceholder,
  nameRequired = false,
  description,
  onDescriptionChange,
  showDescriptionHint = false,
  selectedProviders,
  onToggleProvider,
}: SkillMetadataFieldsProps) {
  return (
    <section className="flex flex-col gap-4">
      <label className="flex flex-col gap-1.5 text-[13px] font-medium" style={{ color: "var(--ink-2)" }}>
        Name {nameRequired && <span style={{ color: "var(--err)" }}>*</span>}
        <input
          className="af-input"
          value={name}
          onChange={(e) => onNameChange(e.target.value)}
          required={nameRequired}
          maxLength={255}
          placeholder={namePlaceholder}
        />
      </label>

      <label className="flex flex-col gap-1.5 text-[13px] font-medium" style={{ color: "var(--ink-2)" }}>
        Description{" "}
        <span className="font-normal" style={{ color: "var(--ink-4)" }}>
          (optional)
        </span>
        <input
          className="af-input"
          value={description}
          onChange={(e) => onDescriptionChange(e.target.value)}
          maxLength={2000}
          placeholder="What this skill helps the agent do"
        />
        {showDescriptionHint && (
          <span className="text-xs font-normal" style={{ color: "var(--ink-4)" }}>
            Shown to the agent alongside the pointer to this skill.
          </span>
        )}
      </label>

      <div className="flex flex-col gap-2">
        <span className="text-[13px] font-medium" style={{ color: "var(--ink-2)" }}>
          Required providers
        </span>
        <div className="flex flex-wrap gap-1.5">
          {ALL_PROVIDERS.map(({ value, label }) => {
            const selected = selectedProviders.includes(value);
            return (
              <button
                key={value}
                type="button"
                onClick={() => onToggleProvider(value)}
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
    </section>
  );
}
