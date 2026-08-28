"use client";

import { FileCode2, KeyRound, Sparkles, UserRound } from "lucide-react";
import { parseAsStringEnum, useQueryState } from "nuqs";

import { SettingsPageLayout } from "@/components/settings/settings-page-layout";
import { SettingsSidebar } from "@/components/settings/settings-sidebar";
import { AgentDefaultsPanel } from "@/features/agent-settings/components/agent-defaults-panel";
import { TemplatesPanel } from "@/features/agents/components/templates-panel";
import { useActiveOrgRole } from "@/features/organizations/hooks/use-active-org-role";
import {
  ORGANIZATION_SETTINGS_SECTION_KEYS,
  visibleOrganizationSettingsSections,
  type OrganizationSettingsSectionKey,
} from "@/features/organizations/components/organization-settings-utils";
import { SharedCredentialsPanel } from "@/features/shared-credentials/components/shared-credentials-panel";
import { SkillsPanel } from "@/features/skills/components/skills-panel";

const ICONS = {
  agents: UserRound,
  templates: FileCode2,
  skills: Sparkles,
  "shared-credentials": KeyRound,
} as const;

export default function SettingsPage() {
  const { canManage, selectedOrganization } = useActiveOrgRole();
  const [activeSection, setActiveSection] = useQueryState(
    "tab",
    parseAsStringEnum<OrganizationSettingsSectionKey>(ORGANIZATION_SETTINGS_SECTION_KEYS)
      .withDefault("agents")
      .withOptions({ scroll: false, history: "replace" }),
  );

  const visibleSections = visibleOrganizationSettingsSections(canManage);
  // A Member who deep-links to an admin-only section lands on the first one they can
  // see rather than an empty page.
  const section =
    visibleSections.find((item) => item.key === activeSection) ?? visibleSections[0];

  if (!section) return null;

  return (
    <div style={{ background: "var(--bg)" }}>
      <main className="af-page">
        <div className="mb-8 flex flex-wrap items-start gap-4">
          <div className="min-w-0 flex-1">
            <h1
              className="m-0 text-[2rem] font-semibold tracking-[-0.025em]"
              style={{ color: "var(--ink)" }}
            >
              Settings
            </h1>
            <p className="mb-0 mt-1 text-[0.9rem]" style={{ color: "var(--ink-3)" }}>
              {selectedOrganization?.name ?? "Organization"}
            </p>
          </div>
          <div
            className="rounded-full border px-3 py-1.5 text-[0.78rem]"
            style={{ borderColor: "var(--line)", color: "var(--ink-3)" }}
          >
            {canManage ? "Admin access" : "Read-only access"}
          </div>
        </div>

        <SettingsPageLayout
          sidebar={
            <SettingsSidebar
              eyebrow="Organization"
              items={visibleSections.map((item) => {
                const Icon = ICONS[item.key];
                return {
                  key: item.key,
                  label: item.label,
                  icon: <Icon size={15} aria-hidden />,
                };
              })}
              activeKey={section.key}
              onSelect={(key) => void setActiveSection(key as OrganizationSettingsSectionKey)}
            />
          }
          heading={section.label}
          description={section.description}
        >
          {section.key === "agents" && <AgentDefaultsPanel canEdit={canManage} />}
          {section.key === "templates" && <TemplatesPanel />}
          {section.key === "skills" && <SkillsPanel scope={{ kind: "organization" }} canManage={canManage} />}
          {section.key === "shared-credentials" && <SharedCredentialsPanel />}
        </SettingsPageLayout>
      </main>
    </div>
  );
}
