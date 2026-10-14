"use client";

import { BookOpenCheck, Brain, Sparkles } from "lucide-react";
import { parseAsStringEnum, useQueryState } from "nuqs";

import { SettingsPageLayout } from "@/components/settings/settings-page-layout";
import { SettingsSidebar } from "@/components/settings/settings-sidebar";
import { PlatformMemorySettings } from "@/features/agent-memory/components/platform-memory-settings";
import { PlatformTrialSettings } from "@/features/onboarding/components/platform-trial-settings";
import { PlatformPlaybookSettings } from "@/features/playbooks/components/platform-playbook-settings";

const SECTIONS = {
  "agent-memory": {
    label: "Agent Memory",
    icon: <Brain size={15} aria-hidden />,
    description: "Long-term memory settings shared by every Agent and Organization.",
  },
  playbooks: {
    label: "Playbooks",
    icon: <BookOpenCheck size={15} aria-hidden />,
    description: "How playbooks are extracted from an Agent's conversations, for every Organization.",
  },
  trials: {
    label: "Trials",
    icon: <Sparkles size={15} aria-hidden />,
    description: "What a new organization gets when someone signs themselves up.",
  },
} as const;

type SectionKey = keyof typeof SECTIONS;

export function PlatformSettings() {
  // In the URL so a section can be linked to, e.g. ?section=playbooks.
  const [active, setActive] = useQueryState(
    "section",
    parseAsStringEnum<SectionKey>(Object.keys(SECTIONS) as SectionKey[])
      .withDefault("agent-memory")
      .withOptions({ scroll: false, history: "replace" }),
  );
  const section = SECTIONS[active];

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
        sidebar={
          <SettingsSidebar
            eyebrow="Platform"
            items={Object.entries(SECTIONS).map(([key, item]) => ({ key, label: item.label, icon: item.icon }))}
            activeKey={active}
            onSelect={(key) => void setActive(key as SectionKey)}
          />
        }
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
