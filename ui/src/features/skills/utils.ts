import { createQueryKeyStructure } from "@/shared/query-keys";

import { skillScopeCacheKey, type SkillScopeRef } from "./scope";

export const skillsKey = createQueryKeyStructure("skills");

// Scoped, not just skillId-keyed: the same skill row reads differently
// depending on which scope's endpoint fetched it (e.g. isAssignedToAgent/
// isPinnedByAgent/hasDraft are computed relative to the caller's scope), so a
// cache hit from one scope's lens must never leak into another's.
export const skillDetailKey = (skillId: string, scope: SkillScopeRef) =>
  [...skillsKey.detail(skillId), skillScopeCacheKey(scope)] as const;
export const skillDraftKey = (skillId: string, scope: SkillScopeRef) =>
  [...skillDetailKey(skillId, scope), "draft"] as const;
export const skillVersionsKey = (skillId: string, scope: SkillScopeRef) =>
  [...skillDetailKey(skillId, scope), "versions"] as const;
export const skillVersionKey = (skillId: string, version: number, scope: SkillScopeRef) =>
  [...skillDetailKey(skillId, scope), "versions", version] as const;
export const SKILLS_PAGE_SIZE = 15;

export const SKILL_PROVIDER_LABELS: Record<string, string> = {
  github: "GitHub",
  jira: "Jira",
  confluence: "Confluence",
  bitbucket: "Bitbucket",
  gmail: "Gmail",
  google_calendar: "Google Calendar",
  google_sheets: "Google Sheets",
  zoho_mail: "Zoho Mail",
  zoho_calendar: "Zoho Calendar",
  slack: "Slack",
  pipedrive: "Pipedrive",
};

export const ALL_PROVIDERS = Object.entries(SKILL_PROVIDER_LABELS).map(
  ([value, label]) => ({ value, label }),
);

/** Entry-point file every custom skill must contain. */
export const DEFAULT_ENTRY_PATH = "SKILL.md";

/** Starting content for a new skill, so authors begin from a shape that works. */
export const NEW_SKILL_TEMPLATE = `# Skill name

Describe what this skill does and when the agent should use it.

## When to use

- ...

## How to use

- ...
`;