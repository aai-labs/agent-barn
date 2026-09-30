import { Badge } from "@/components/badge";

import type { SkillScope } from "../schemas";

const LABELS: Record<SkillScope, string> = {
  platform: "Platform",
  organization: "Organization",
  agent: "Agent-private",
};

/** Which of the three owning tiers a skill belongs to — distinct from
 * SkillSourceBadge's Built-in/Custom, and most useful wherever skills from more
 * than one scope are listed together (e.g. an Agent's combined skill list). */
export function SkillScopeBadge({ scope }: { scope: SkillScope }) {
  return <Badge variant={scope === "agent" ? "accent" : "neutral"}>{LABELS[scope]}</Badge>;
}
