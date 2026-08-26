import { FileCode2, History } from "lucide-react";

export type SkillDetailSection = "files" | "history";

const SECTIONS: { key: SkillDetailSection; label: string; icon: typeof FileCode2 }[] = [
  { key: "files", label: "Files", icon: FileCode2 },
  { key: "history", label: "Version history", icon: History },
];

export function SkillDetailSidebar({
  activeSection,
  onSectionChange,
}: {
  activeSection: SkillDetailSection;
  onSectionChange: (section: SkillDetailSection) => void;
}) {
  return (
    <aside className="w-full flex-shrink-0 lg:sticky lg:top-[77px] lg:w-56">
      <div
        className="mb-3 px-3 text-[0.7rem] font-semibold uppercase tracking-[0.1em]"
        style={{ color: "var(--ink-4)" }}
      >
        Skill
      </div>
      <nav className="flex gap-1 overflow-x-auto lg:flex-col lg:overflow-visible">
        {SECTIONS.map(({ key, label, icon: Icon }) => {
          const isActive = activeSection === key;
          return (
            <button
              key={key}
              type="button"
              className="flex min-w-max items-center gap-2 rounded-lg px-3 py-2 text-left text-[0.82rem] font-medium transition-colors lg:w-full"
              style={{
                background: isActive ? "var(--bg-soft)" : "transparent",
                color: isActive ? "var(--ink)" : "var(--ink-3)",
                fontWeight: isActive ? 600 : 500,
              }}
              aria-current={isActive ? "page" : undefined}
              onClick={() => onSectionChange(key)}
            >
              <Icon size={15} aria-hidden />
              <span>{label}</span>
            </button>
          );
        })}
      </nav>
    </aside>
  );
}
