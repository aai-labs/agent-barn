"use client";

import { BookOpenCheck, Brain, Building2, CreditCard, Gauge, KeyRound, Layers, Scale, Sparkles, Workflow } from "lucide-react";
import { parseAsStringEnum, useQueryState } from "nuqs";

import { SettingsPageLayout } from "@/components/settings/settings-page-layout";
import { PlatformMemorySettings } from "@/features/agent-memory/components/platform-memory-settings";
import { AgentSizesSettings } from "@/features/agent-sizes/components/agent-sizes-settings";
import { PlatformBillingSettings } from "@/features/billing/components/platform-billing-settings";
import { PlatformDecisionSettings } from "@/features/decisions/components/platform-decision-settings";
import { PlatformLlmProviderSettings } from "@/features/llm-providers/components/platform-llm-provider-settings";
import { PlatformTrialSettings } from "@/features/onboarding/components/platform-trial-settings";
import { PlatformOrganizationSettings } from "@/features/organizations/components/platform-organization-settings";
import { PlatformPlaybookSettings } from "@/features/playbooks/components/platform-playbook-settings";
import { TiersSettings } from "@/features/tiers/components/tiers-settings";
import { PlatformWorkflowSettings } from "@/features/workflows/components/platform-workflow-settings";

export const PLATFORM_SETTINGS_SECTIONS = {
  "agent-memory": {
    label: "Agent Memory",
    Icon: Brain,
    description: "Long-term memory settings shared by every Agent and Organization.",
  },
  "llm-providers": {
    label: "LLM providers",
    Icon: KeyRound,
    description: "The provider accounts Agents reach models through, for every Organization.",
  },
  "agent-sizes": {
    label: "Agent sizes",
    Icon: Gauge,
    description: "The CPU and memory Agents run with. Every Agent runs on the default size.",
  },
  organizations: {
    label: "Organizations",
    Icon: Building2,
    description: "What every organization gets unless you set something else for it.",
  },
  workflows: {
    label: "Workflows",
    Icon: Workflow,
    description: "Workflow authoring shared by every Agent and Organization.",
  },
  playbooks: {
    label: "Playbooks",
    Icon: BookOpenCheck,
    description: "How playbooks are extracted from an Agent's conversations, for every Organization.",
  },
  decisions: {
    label: "Decisions",
    Icon: Scale,
    description: "The model that answers the platform's questions about Agents, for every Organization.",
  },
  trials: {
    label: "Signup & trials",
    Icon: Sparkles,
    description: "Manage public signup and what each new trial organization receives.",
  },
  tiers: {
    label: "Tiers",
    Icon: Layers,
    description: "What organizations may use and what they pay for it.",
  },
  billing: {
    label: "Billing",
    Icon: CreditCard,
    description: "How organizations buy the credit their agents spend.",
  },
} as const;

export type PlatformSettingsSectionKey = keyof typeof PLATFORM_SETTINGS_SECTIONS;
type SectionKey = PlatformSettingsSectionKey;

export function PlatformSettings() {
  // In the URL so a section can be linked to, e.g. ?section=playbooks.
  const [active] = useQueryState(
    "section",
    parseAsStringEnum<SectionKey>(Object.keys(PLATFORM_SETTINGS_SECTIONS) as SectionKey[])
      .withDefault("agent-memory")
      .withOptions({ scroll: false, history: "replace" }),
  );
  const section = PLATFORM_SETTINGS_SECTIONS[active];

  return (
    <div>
      <SettingsPageLayout
        heading={section.label}
        description={section.description}
      >
        {active === "agent-memory" && <PlatformMemorySettings />}
        {active === "llm-providers" && <PlatformLlmProviderSettings />}
        {active === "agent-sizes" && <AgentSizesSettings />}
        {active === "organizations" && <PlatformOrganizationSettings />}
        {active === "workflows" && <PlatformWorkflowSettings />}
        {active === "playbooks" && <PlatformPlaybookSettings />}
        {active === "decisions" && <PlatformDecisionSettings />}
        {active === "trials" && <PlatformTrialSettings />}
        {active === "tiers" && <TiersSettings />}
        {active === "billing" && <PlatformBillingSettings />}
      </SettingsPageLayout>
    </div>
  );
}
