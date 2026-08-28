"use client";

import { Loader2, Pencil } from "lucide-react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useSkills } from "@/features/skills/hooks/use-skills";
import { PlatformTemplateSkillCheckbox } from "@/features/platform-templates/components/platform-template-skill-checkbox";
import { PlatformTemplateSkillGroup } from "@/features/platform-templates/components/platform-template-skill-group";
import { PLATFORM_TEMPLATE_FILES } from "@/features/platform-templates/utils";

import type { AgentOverrideDraft } from "../schemas";
import {
  draftToForm,
  type DraftForm,
  type DraftTextField,
  type RequiredSkillGroupDraft,
} from "./agent-configuration-utils";
import { ConfigurationArtifactSurface } from "./configuration-artifact-surface";
import { ConfigurationRequiredSkills } from "./configuration-required-skills";
import { ConfigurationSnapshotMeta } from "./configuration-snapshot-meta";

export function AgentOverrideDraftEditor({
  draft,
  form,
  onChange,
  onRequirementsChange,
  onSave,
  onCancel,
  isSaving,
}: {
  draft: AgentOverrideDraft;
  form: DraftForm;
  onChange: (field: DraftTextField, value: string) => void;
  onRequirementsChange: (
    skillIds: string[],
    groups: RequiredSkillGroupDraft[],
  ) => void;
  onSave: () => void;
  onCancel: () => void;
  isSaving: boolean;
}) {
  const { skills, isLoading: skillsLoading } = useSkills({ scope: { kind: "organization" }, pageSize: 100 });
  const original = draftToForm(draft);
  const isDirty =
    PLATFORM_TEMPLATE_FILES.some(({ key }) => form[key] !== original[key]) ||
    form.templateName !== original.templateName ||
    form.description !== original.description ||
    JSON.stringify(form.requiredSkillIds) !==
      JSON.stringify(original.requiredSkillIds) ||
    JSON.stringify(form.requiredSkillGroups) !==
      JSON.stringify(original.requiredSkillGroups);
  const selectedSkillIds = new Set([
    ...form.requiredSkillIds,
    ...form.requiredSkillGroups.flatMap((group) => group.skillIds),
  ]);
  const skillMap = new Map(skills.map((skill) => [skill.id, skill]));
  const groupedSkillIds = new Set(
    form.requiredSkillGroups.flatMap((group) => group.skillIds),
  );
  const standaloneSkills = skills.filter(
    (skill) => !groupedSkillIds.has(skill.id),
  );

  const toggleSkill = (skillId: string) => {
    const group = form.requiredSkillGroups.find((item) =>
      item.skillIds.includes(skillId),
    );
    if (group) {
      if (group.skillIds.length <= 1) return;
      onRequirementsChange(
        form.requiredSkillIds,
        form.requiredSkillGroups
          .map((item) =>
            item.groupKey === group.groupKey
              ? {
                  ...item,
                  skillIds: item.skillIds.filter((id) => id !== skillId),
                }
              : item,
          )
          .filter((item) => item.skillIds.length > 0),
      );
      return;
    }

    onRequirementsChange(
      form.requiredSkillIds.includes(skillId)
        ? form.requiredSkillIds.filter((id) => id !== skillId)
        : [...form.requiredSkillIds, skillId],
      form.requiredSkillGroups,
    );
  };

  return (
    <section className="af-card overflow-hidden">
      <div
        className="border-b px-5 py-4"
        style={{ borderColor: "var(--line)" }}
      >
        <div className="flex items-center gap-2">
          <Pencil size={15} style={{ color: "var(--accent-ink)" }} />
          <h2
            className="m-0 text-[1rem] font-semibold"
            style={{ color: "var(--ink)" }}
          >
            Override Draft
          </h2>
        </div>
        <div className="mt-1">
          <ConfigurationSnapshotMeta snapshot={draft} />
        </div>
        <p
          className="mb-0 mt-2 text-[0.78rem]"
          style={{ color: "var(--ink-3)" }}
        >
          Drafts are Agent-owned. Publishing creates a new immutable version
          and does not switch the active pin.
        </p>
      </div>

      <div className="p-5">
        <div className="mb-4 max-w-xl">
          <Label
            htmlFor="override-template-name"
            className="mb-2"
            style={{ color: "var(--ink-2)" }}
          >
            Template name
          </Label>
          <Input
            id="override-template-name"
            value={form.templateName}
            onChange={(event) => onChange("templateName", event.target.value)}
            required
          />
        </div>
        <div className="mb-4 max-w-xl">
          <Label
            htmlFor="override-description"
            className="mb-2"
            style={{ color: "var(--ink-2)" }}
          >
            Description
          </Label>
          <Input
            id="override-description"
            value={form.description}
            onChange={(event) => onChange("description", event.target.value)}
            placeholder="What this Agent-specific configuration is for"
          />
        </div>

        <ConfigurationArtifactSurface
          snapshot={draft}
          editable
          values={form}
          onChange={(artifact, value) => onChange(artifact, value)}
        />

        <div className="mt-5">
          <div
            className="mb-2 text-[0.75rem] font-semibold uppercase tracking-[0.08em]"
            style={{ color: "var(--ink-4)" }}
          >
            Required skills
          </div>
          {skillsLoading ? (
            <p className="m-0 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
              Loading available skills…
            </p>
          ) : skills.length === 0 ? (
            <p className="m-0 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
              No available skills.
            </p>
          ) : (
            <div className="flex flex-col gap-3">
              {form.requiredSkillGroups.map((group) => (
                <PlatformTemplateSkillGroup
                  key={group.groupKey}
                  group={group}
                  skills={skills}
                  skillMap={skillMap}
                  selectedSkillIds={selectedSkillIds}
                  onToggle={toggleSkill}
                />
              ))}
              <div className="grid gap-2 sm:grid-cols-2">
                {standaloneSkills.map((skill) => (
                  <PlatformTemplateSkillCheckbox
                    key={skill.id}
                    skill={skill}
                    checked={selectedSkillIds.has(skill.id)}
                    onChange={() => toggleSkill(skill.id)}
                  />
                ))}
              </div>
            </div>
          )}
          <p
            className="mb-0 mt-2 text-[0.76rem]"
            style={{ color: "var(--ink-4)" }}
          >
            Skills are validated against the Agent&apos;s assignments and
            configured providers when the draft is published.
          </p>
        </div>
        <ConfigurationRequiredSkills snapshot={draft} />
      </div>

      <footer
        className="flex flex-wrap items-center justify-end gap-2 border-t px-5 py-3"
        style={{ borderColor: "var(--line)" }}
      >
        <button
          className="af-btn"
          type="button"
          disabled={isSaving}
          onClick={onCancel}
        >
          Cancel
        </button>
        <button
          className="af-btn af-btn-primary"
          type="button"
          disabled={!isDirty || isSaving}
          onClick={onSave}
        >
          {isSaving && <Loader2 size={14} className="animate-spin" />}
          {isSaving ? "Saving…" : "Save draft"}
        </button>
      </footer>
    </section>
  );
}
