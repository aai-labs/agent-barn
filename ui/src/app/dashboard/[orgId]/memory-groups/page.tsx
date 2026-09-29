"use client";

import { MemoryGroupsPanel } from "@/features/memory-groups/components/memory-groups-panel";
import { useActiveOrgRole } from "@/features/organizations/hooks/use-active-org-role";

export default function MemoryGroupsRoute() {
  const { selectedOrganization } = useActiveOrgRole();

  return (
    <div style={{ background: "var(--bg)" }}>
      <main className="af-page">
        <div className="mb-8">
          <h1 className="m-0 text-[2rem] font-semibold tracking-[-0.025em]" style={{ color: "var(--ink)" }}>
            Memory Groups
          </h1>
          <p className="mb-0 mt-1 text-[0.9rem]" style={{ color: "var(--ink-3)" }}>
            {selectedOrganization?.name ?? "Organization"} · groups of Agents that share what they
            learn, so each can draw on the others&rsquo; memory.
          </p>
        </div>
        <MemoryGroupsPanel />
      </main>
    </div>
  );
}
