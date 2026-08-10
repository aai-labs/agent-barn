import { Check } from "lucide-react";

import type { PlatformSkill } from "../schemas";

export function PlatformTemplateSkillCheckbox({
  skill,
  checked,
  onChange,
}: {
  skill: PlatformSkill;
  checked: boolean;
  onChange: () => void;
}) {
  return (
    <label
      className="flex items-center gap-3 rounded-xl px-3 py-2.5 cursor-pointer"
      style={{ border: "1px solid var(--line)" }}
    >
      <input
        type="checkbox"
        checked={checked}
        onChange={onChange}
        className="accent-[var(--accent-color)]"
      />
      <span className="flex-1 min-w-0">
        <span
          className="block text-[13px] font-medium truncate"
          style={{ color: "var(--ink-2)" }}
        >
          {skill.name}
        </span>
        <span className="block text-[11.5px]" style={{ color: "var(--ink-4)" }}>
          Global platform skill
        </span>
      </span>
      {checked && <Check size={14} style={{ color: "var(--ok)" }} />}
    </label>
  );
}
