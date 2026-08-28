import { useState } from "react";
import { Check } from "lucide-react";

import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useSkillVersions } from "@/features/skills/hooks/use-skill-versions";

import type { PlatformSkill } from "../schemas";

export function PlatformTemplateSkillCheckbox({
  skill,
  checked,
  onChange,
  version,
  onVersionChange,
  showVersionPicker = false,
  disabled = false,
}: {
  skill: PlatformSkill;
  checked: boolean;
  onChange: () => void;
  version?: number | null;
  onVersionChange?: (version: number) => void;
  showVersionPicker?: boolean;
  disabled?: boolean;
}) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const { versions, isLoading } = useSkillVersions(
    skill.id,
    { kind: "platform" },
    showVersionPicker && pickerOpen && checked,
  );
  const selectedVersion = version ?? skill.version;
  const options =
    showVersionPicker && pickerOpen && versions.length > 0
      ? versions.map((item) => item.version)
      : selectedVersion === null
        ? []
        : [selectedVersion];
  const unavailable = showVersionPicker && selectedVersion === null;

  return (
    <div
      className={`flex items-center gap-3 rounded-xl px-3 py-2.5 ${disabled || unavailable ? "cursor-not-allowed opacity-60" : ""}`}
      style={{ border: "1px solid var(--line)" }}
    >
      <label className={`flex items-center gap-3 flex-1 min-w-0 ${disabled || unavailable ? "cursor-not-allowed" : "cursor-pointer"}`}>
        <input
          type="checkbox"
          checked={checked}
          disabled={disabled || unavailable}
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
            {unavailable ? "No published version" : "Global platform skill"}
          </span>
        </span>
      </label>
      {showVersionPicker && checked && (
        <Select
          value={selectedVersion === null ? "" : String(selectedVersion)}
          onValueChange={(value) => onVersionChange?.(Number(value))}
          onOpenChange={setPickerOpen}
          disabled={disabled || unavailable}
        >
          <SelectTrigger
            className="w-auto min-w-24"
            aria-label={`Required version for ${skill.name}`}
            title="Choose the exact published Skill Version required by this Template."
          >
            <SelectValue placeholder="Version" />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              {options.map((item) => (
                <SelectItem key={item} value={String(item)}>
                  Version v{item}
                </SelectItem>
              ))}
              {showVersionPicker && pickerOpen && isLoading && options.length === 0 && (
                <div className="px-2 py-1.5 text-[0.78rem]" style={{ color: "var(--ink-4)" }}>
                  Loading versions…
                </div>
              )}
            </SelectGroup>
          </SelectContent>
        </Select>
      )}
      {checked && <Check size={14} style={{ color: "var(--ok)" }} />}
    </div>
  );
}
