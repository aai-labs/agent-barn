"use client";

import { parseAsStringEnum, useQueryState } from "nuqs";

import { SettingsPageLayout } from "@/components/settings/settings-page-layout";
import { MemoryItemsViewer } from "@/features/agent-memory/components/memory-items-viewer";
import { MemoryAccessPanel } from "@/features/agent-memory/components/memory-access-panel";
import { AgentDefaultsPanel } from "@/features/agent-settings/components/agent-defaults-panel";
import { TemplatesPanel } from "@/features/templates/components/templates-panel";
import { useActiveOrgRole } from "@/features/organizations/hooks/use-active-org-role";
import {
  ORGANIZATION_SETTINGS_SECTION_KEYS,
  visibleOrganizationSettingsSections,
  type OrganizationSettingsSectionKey,
} from "@/features/organizations/components/organization-settings-utils";
import { SharedCredentialsPanel } from "@/features/shared-credentials/components/shared-credentials-panel";
import { SkillsPanel } from "@/features/skills/components/skills-panel";
import { SpendLimitsPanel } from "@/features/spend-limits/components/spend-limits-panel";
import { SyncProvidersPanel } from "@/features/sync-provider/components/sync-providers-panel";


export default function SettingsPage() {
  const { role, canManage, selectedOrganization } = useActiveOrgRole();
  const isMembershipAdmin = role === "OWNER" || role === "ADMIN";
  const [activeSection] = useQueryState(
    "tab",
    parseAsStringEnum<OrganizationSettingsSectionKey>(ORGANIZATION_SETTINGS_SECTION_KEYS)
      .withDefault("agents")
      .withOptions({ scroll: false, history: "replace" }),
  );

  const visibleSections = visibleOrganizationSettingsSections(canManage, isMembershipAdmin);
  // A Member who deep-links to an admin-only section lands on the first one they can
  // see rather than an empty page.
  const section =
    visibleSections.find((item) => item.key === activeSection) ?? visibleSections[0];

  if (!section) return null;

  return (
    <div style={{ background: "var(--bg)" }}>
      <main className="af-page">
        <SettingsPageLayout
          heading={section.label}
          description={section.description}
          aside={
            <div
              className="rounded-full border px-3 py-1.5 text-[0.78rem]"
              style={{ borderColor: "var(--line)", color: "var(--ink-3)" }}
            >
              {canManage ? "Admin access" : "Read-only access"}
            </div>
          }
        >
          {section.key === "agents" && <AgentDefaultsPanel canEdit={canManage} />}
          {section.key === "spend-limits" && <SpendLimitsPanel />}
          {section.key === "templates" && (
            <TemplatesPanel scope={{ kind: "organization" }} canManage={canManage} />
          )}
          {section.key === "skills" && <SkillsPanel scope={{ kind: "organization" }} canManage={canManage} />}
          {section.key === "organization-memory" && <MemoryItemsViewer key={selectedOrganization?.id} enabled={isMembershipAdmin} />}
          {section.key === "memory-access" && <MemoryAccessPanel canManage={isMembershipAdmin} />}
          {section.key === "shared-credentials" && <SharedCredentialsPanel />}
          {section.key === "sync" && <SyncProvidersPanel canManage={canManage} />}
        </SettingsPageLayout>
      </main>
    </div>
  );
}
