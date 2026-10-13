"use client";

import { BookOpenCheck, Brain } from "lucide-react";
import { parseAsStringEnum, useQueryState } from "nuqs";

import { SettingsPageLayout } from "@/components/settings/settings-page-layout";
import { SettingsSidebar } from "@/components/settings/settings-sidebar";
import { PlatformMemorySettings } from "@/features/agent-memory/components/platform-memory-settings";
import { PlatformPlaybookSettings } from "@/features/playbooks/components/platform-playbook-settings";

const SECTIONS = [
  {
    key: "agent-memory",
    label: "Agent Memory",
    description: "Long-term memory settings shared by every Agent and Organization.",
    icon: Brain,
  },
  {
    key: "playbooks",
    label: "Playbooks",
    description: "How playbooks are extracted from an Agent's conversations, for every Organization.",
    icon: BookOpenCheck,
  },
] as const;

type SectionKey = (typeof SECTIONS)[number]["key"];

export function PlatformSettingsPage() {
  const [active, setActive] = useQueryState(
    "section",
    parseAsStringEnum<SectionKey>(SECTIONS.map((section) => section.key))
      .withDefault("agent-memory")
      .withOptions({ scroll: false, history: "replace" }),
  );
  const section = SECTIONS.find((item) => item.key === active) ?? SECTIONS[0];

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
            items={SECTIONS.map((item) => {
              const Icon = item.icon;
              return { key: item.key, label: item.label, icon: <Icon size={15} aria-hidden /> };
            })}
            activeKey={section.key}
            onSelect={(key) => void setActive(key as SectionKey)}
          />
        }
        heading={section.label}
        description={section.description}
      >
        {section.key === "agent-memory" && <PlatformMemorySettings />}
        {section.key === "playbooks" && <PlatformPlaybookSettings />}
      </SettingsPageLayout>
    </div>
  );
}
