"use client";

import { BookOpenCheck, Brain, Sparkles, Workflow } from "lucide-react";
import { parseAsStringEnum, useQueryState } from "nuqs";

import { SettingsPageLayout } from "@/components/settings/settings-page-layout";
import { PlatformMemorySettings } from "@/features/agent-memory/components/platform-memory-settings";
import { PlatformTrialSettings } from "@/features/onboarding/components/platform-trial-settings";
import { PlatformPlaybookSettings } from "@/features/playbooks/components/platform-playbook-settings";
import { PlatformWorkflowSettings } from "@/features/workflows/components/platform-workflow-settings";

export const PLATFORM_SETTINGS_SECTIONS = {
  "agent-memory": {
    label: "Agent Memory",
    Icon: Brain,
    description: "Long-term memory settings shared by every Agent and Organization.",
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
  trials: {
    label: "Signup & trials",
    Icon: Sparkles,
    description: "Manage public signup and what each new trial organization receives.",
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
    <div className="af-page">
      <SettingsPageLayout
        heading={section.label}
        description={section.description}
      >
        {active === "agent-memory" && <PlatformMemorySettings />}
        {active === "workflows" && <PlatformWorkflowSettings />}
        {active === "playbooks" && <PlatformPlaybookSettings />}
        {active === "trials" && <PlatformTrialSettings />}
      </SettingsPageLayout>
    </div>
  );
}
