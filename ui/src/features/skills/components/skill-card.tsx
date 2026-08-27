import Link from "next/link";
import { Plus, Sparkles } from "lucide-react";

import { Badge } from "@/components/badge";

import type { Skill } from "../schemas";
import { SKILL_PROVIDER_LABELS } from "../utils";
import { SkillScopeBadge } from "./skill-scope-badge";
import { SkillSourceBadge } from "./skill-source-badge";

export function SkillCard({
  skill,
  href,
  onAdd,
  addDisabled = false,
}: {
  skill: Skill;
  href: string;
  onAdd?: () => void;
  addDisabled?: boolean;
}) {
  return (
    <article className="af-card af-card-hover flex h-full flex-col overflow-hidden">
      <Link href={href} className="block flex-1 px-5 py-5 text-left no-underline">
        <div className="flex items-start justify-between gap-3 mb-2">
          <div className="flex items-center gap-2 min-w-0">
            <Sparkles size={15} style={{ color: "var(--ink-4)", flexShrink: 0 }} />
            <span className="font-semibold text-[15px] truncate" style={{ color: "var(--ink)" }}>
              {skill.name}
            </span>
          </div>
          <div className="flex items-center gap-1.5 flex-shrink-0">
            {skill.hasDraft && <Badge variant="warn">Draft</Badge>}
            <SkillScopeBadge scope={skill.scope} />
            <SkillSourceBadge source={skill.source} />
          </div>
        </div>

        {skill.description && (
          <p
            className="text-[12.5px] leading-[1.5] m-0 mb-3 line-clamp-2"
            style={{ color: "var(--ink-3)" }}
          >
            {skill.description}
          </p>
        )}

        {skill.requiredProviders.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-3">
            {skill.requiredProviders.map((p) => (
              <span
                key={p}
                className="inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium"
                style={{ background: "var(--bg-soft)", color: "var(--ink-3)", border: "1px solid var(--line)" }}
              >
                {SKILL_PROVIDER_LABELS[p] ?? p}
              </span>
            ))}
          </div>
        )}

        <div
          className="flex items-center justify-between text-[12.5px] pt-3"
          style={{ color: "var(--ink-3)", borderTop: "1px solid var(--line)" }}
        >
          <span>v{skill.version}</span>
          <span className="font-mono" style={{ color: "var(--ink-4)" }}>
            ./skills/{skill.rootDir}
          </span>
        </div>
      </Link>

      {onAdd && (
        <div
          className="flex justify-end border-t bg-[var(--bg-soft)] px-5 py-3"
          style={{ borderColor: "var(--line)" }}
        >
          <button
            type="button"
            className="af-btn af-btn-sm af-btn-primary"
            disabled={addDisabled}
            onClick={onAdd}
          >
            <Plus size={13} />
            Add
          </button>
        </div>
      )}
    </article>
  );
}
