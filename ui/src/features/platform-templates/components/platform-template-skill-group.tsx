import type { PlatformSkill } from "../schemas";
import type { SkillGroupDraft } from "../utils";
import { PlatformTemplateSkillCheckbox } from "./platform-template-skill-checkbox";

export function PlatformTemplateSkillGroup({
  group,
  skills,
  skillMap,
  selectedSkillIds,
  onToggle,
}: {
  group: SkillGroupDraft;
  skills: PlatformSkill[];
  skillMap: Map<string, PlatformSkill>;
  selectedSkillIds: Set<string>;
  onToggle: (skillId: string) => void;
}) {
  const groupSkills = group.skillIds
    .map((id) => skillMap.get(id))
    .filter((skill): skill is PlatformSkill => Boolean(skill));
  const visibleGroupSkills = skills.filter((skill) =>
    group.skillIds.includes(skill.id),
  );
  const missingSkillCount = group.skillIds.length - groupSkills.length;

  return (
    <div
      className="rounded-xl p-3 flex flex-col gap-2"
      style={{
        border: "1px solid var(--line-strong)",
        background: "var(--bg-soft)",
      }}
    >
      <div className="flex items-center justify-between gap-3">
        <div>
          <div
            className="text-[12px] uppercase tracking-[0.07em] font-semibold"
            style={{ color: "var(--ink-3)" }}
          >
            At least one of
          </div>
          <div
            className="font-mono text-[12px] mt-0.5"
            style={{ color: "var(--ink-2)" }}
          >
            {group.groupKey}
          </div>
        </div>
        <span className="text-[11.5px]" style={{ color: "var(--ink-4)" }}>
          {group.skillIds.length} skills
        </span>
      </div>
      {visibleGroupSkills.map((skill) => (
        <PlatformTemplateSkillCheckbox
          key={skill.id}
          skill={skill}
          checked={selectedSkillIds.has(skill.id)}
          onChange={() => onToggle(skill.id)}
        />
      ))}
      {missingSkillCount > 0 && (
        <div className="text-[11.5px]" style={{ color: "var(--warn)" }}>
          {missingSkillCount} required skill
          {missingSkillCount === 1 ? " is" : "s are"} not in the current global
          catalog.
        </div>
      )}
      {groupSkills.length === 1 && (
        <div className="text-[11.5px]" style={{ color: "var(--ink-4)" }}>
          One member must remain selected.
        </div>
      )}
    </div>
  );
}
