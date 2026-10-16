"use client";

import { BookOpenCheck, Brain, Sparkles } from "lucide-react";
import { parseAsStringEnum, useQueryState } from "nuqs";

import { SettingsPageLayout } from "@/components/settings/settings-page-layout";
import { PlatformMemorySettings } from "@/features/agent-memory/components/platform-memory-settings";
import { PlatformTrialSettings } from "@/features/onboarding/components/platform-trial-settings";
import { PlatformPlaybookSettings } from "@/features/playbooks/components/platform-playbook-settings";

export const PLATFORM_SETTINGS_SECTIONS = {
  "agent-memory": {
    label: "Agent Memory",
    Icon: Brain,
    description: "Long-term memory settings shared by every Agent and Organization.",
  },
  playbooks: {
    label: "Playbooks",
    Icon: BookOpenCheck,
    description: "How playbooks are extracted from an Agent's conversations, for every Organization.",
  },
  trials: {
    label: "Trials",
    Icon: Sparkles,
    description: "What a new organization gets when someone signs themselves up.",
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
      <div className="mb-8 flex flex-wrap items-start gap-4">
        <div className="min-w-0 flex-1">
          <h1 className="m-0 text-[2rem] font-semibold tracking-[-0.025em]" style={{ color: "var(--ink)" }}>
            Settings
          </h1>
          <p className="mb-0 mt-1 text-[0.9rem]" style={{ color: "var(--ink-3)" }}>
            Platform
          </p>
        </div>
        <div
          className="rounded-full border px-3 py-1.5 text-[0.78rem]"
          style={{ borderColor: "var(--line)", color: "var(--ink-3)" }}
        >
          Admin access
        </div>
      </div>
      <SettingsPageLayout
        heading={section.label}
        description={section.description}
      >
        {active === "agent-memory" && <PlatformMemorySettings />}
        {active === "playbooks" && <PlatformPlaybookSettings />}
        {active === "trials" && <PlatformTrialSettings />}
      </SettingsPageLayout>
    </div>
  );
}
