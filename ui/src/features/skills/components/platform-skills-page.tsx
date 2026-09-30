"use client";

import { useCurrentUser } from "@/auth/providers/user-context-provider";

import { SkillsPanel } from "./skills-panel";

/** The Platform View's Skill catalogue. Reuses the same list/search/filter/create
 * surface as Organization Skills — only the scope (and therefore the API base
 * path, permission source, and available actions) differs. */
export function PlatformSkillsPage() {
  const { user } = useCurrentUser();

  return (
    <div className="max-w-[1200px] mx-auto px-10 pt-9 pb-24">
      <div className="mb-8">
        <h1 className="text-[28px] font-semibold tracking-tight m-0 mb-1" style={{ color: "var(--ink)" }}>
          Platform skills
        </h1>
        <p className="text-[14px] m-0" style={{ color: "var(--ink-3)" }}>
          Manage the global Skill catalogue — including the bundled aai-cli integrations —
          available to every organization and agent.
        </p>
      </div>

      <SkillsPanel scope={{ kind: "platform" }} canManage={user.isPlatformAdmin} />
    </div>
  );
}
