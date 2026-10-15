"use client";

import { Brain, Sparkles, Workflow } from "lucide-react";
import { parseAsStringLiteral, useQueryState } from "nuqs";

import { SettingsPageLayout } from "@/components/settings/settings-page-layout";
import { SettingsSidebar } from "@/components/settings/settings-sidebar";
import { PlatformMemorySettings } from "@/features/agent-memory/components/platform-memory-settings";
import { PlatformTrialSettings } from "@/features/onboarding/components/platform-trial-settings";
import { PlatformWorkflowSettings } from "@/features/workflows/components/platform-workflow-settings";

const SECTIONS = {
  "agent-memory": {
    label: "Agent Memory",
    icon: <Brain size={15} aria-hidden />,
    description: "Long-term memory settings shared by every Agent and Organization.",
  },
  workflows: {
    label: "Workflows",
    icon: <Workflow size={15} aria-hidden />,
    description: "Workflow authoring shared by every Agent and Organization.",
  },
  trials: {
    label: "Signup & trials",
    icon: <Sparkles size={15} aria-hidden />,
    description: "Manage public signup and what each new trial organization receives.",
  },
} as const;

export function PlatformSettings() {
  const [active, setActive] = useQueryState(
    "section",
    parseAsStringLiteral(["agent-memory", "workflows", "trials"]).withDefault("agent-memory"),
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
            onSelect={(key) => void setActive(key === "workflows" || key === "trials" ? key : "agent-memory")}
          />
        }
        heading={section.label}
        description={section.description}
      >
        {active === "agent-memory" ? (
          <PlatformMemorySettings />
        ) : active === "workflows" ? (
          <PlatformWorkflowSettings />
        ) : (
          <PlatformTrialSettings />
        )}
      </SettingsPageLayout>
    </div>
  );
}
