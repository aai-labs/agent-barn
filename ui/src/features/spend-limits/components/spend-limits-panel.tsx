"use client";

import { useState } from "react";

import { AgentDefaultSpendLimitSection } from "@/features/agent-settings/components/agent-default-spend-limit-section";
import { useOrganizationLlmBudget } from "@/features/organizations/hooks/use-organization-llm-budget";
import { periodLabel, windowLabel } from "@/features/organizations/spend-limit";

import { AgentLimitsTable } from "./agent-limits-table";
import { OrganizationLimitSection } from "./organization-limit-section";

type SectionKey = "organization" | "default";

function Heading({ children }: { children: string }) {
  return (
    <h3 className="m-0 mb-2 text-[0.95rem] font-semibold" style={{ color: "var(--ink)" }}>
      {children}
    </h3>
  );
}

/**
 * Every spend limit an organization controls, in the order they bind: its own limit,
 * the default its Agents follow, and the Agents with a limit of their own. One place,
 * because each level is held beneath the one above it and a change at the top moves
 * everything under it.
 */
export function SpendLimitsPanel() {
  // One card edits at a time, matching the other settings surfaces.
  const [editing, setEditing] = useState<SectionKey | null>(null);
  const { budget } = useOrganizationLlmBudget();
  const toggle = (section: SectionKey) => () => setEditing((current) => (current === section ? null : section));

  return (
    <div className="flex flex-col gap-8">
      <section>
        <Heading>Organization limit</Heading>
        <OrganizationLimitSection editing={editing === "organization"} onEdit={toggle("organization")} />
      </section>
      <section>
        <Heading>Default Agent limit</Heading>
        <AgentDefaultSpendLimitSection editing={editing === "default"} onEdit={toggle("default")} />
      </section>
      <section>
        <Heading>Agent limits</Heading>
        <AgentLimitsTable period={periodLabel(budget?.window)} per={windowLabel(budget?.window)} />
      </section>
    </div>
  );
}
