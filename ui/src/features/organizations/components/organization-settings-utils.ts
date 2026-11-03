import { Brain, FileCode2, FolderSync, KeyRound, Sparkles, UserRound, Wallet } from "lucide-react";

export type OrganizationSettingsSectionKey =
  | "agents"
  | "spend-limits"
  | "templates"
  | "skills"
  | "organization-memory"
  | "memory-access"
  | "shared-credentials"
  | "sync";

export type OrganizationSettingsSection = {
  key: OrganizationSettingsSectionKey;
  label: string;
  /** Rendered under the section heading, so it says what the section is for. */
  description: string;
  /** Hidden from Members entirely, the way Shared Credentials already is. */
  adminOnly: boolean;
  /**
   * Needs an Owner or Admin membership in this Organization specifically. A platform
   * administrator who is only a Member does not hold `memory.access.manage`.
   */
  membershipAdminOnly?: boolean;
};

export const ORGANIZATION_SETTINGS_SECTIONS: OrganizationSettingsSection[] = [
  {
    key: "agents",
    label: "Models",
    description:
      "Choose the default model and the models available to Agents in this organization.",
    adminOnly: true,
  },
  {
    key: "spend-limits",
    label: "Spend limits",
    description:
      "The most your organization and each of its Agents can spend on model calls. Each limit is held beneath the one above it.",
    adminOnly: true,
  },
  {
    key: "templates",
    label: "Templates",
    description: "Reusable Agent definitions your team can hire from.",
    adminOnly: false,
  },
  {
    key: "skills",
    label: "Skills",
    description: "Vetted tools your Agents are allowed to call.",
    adminOnly: false,
  },
  {
    key: "organization-memory",
    label: "Organization Memory",
    description: "Shared knowledge saved by your Agents for this Organization.",
    adminOnly: true,
    membershipAdminOnly: true,
  },
  {
    key: "memory-access",
    label: "Memory access",
    description: "Which Agents may recall each other's memories or share Organization Memory.",
    adminOnly: true,
    membershipAdminOnly: true,
  },
  {
    key: "shared-credentials",
    label: "Shared Credentials",
    description: "Organization-wide integration keys reusable across Agents.",
    adminOnly: true,
  },
  {
    key: "sync",
    label: "Sync",
    description: "Connect storage providers to keep your organization's files in sync.",
    adminOnly: false,
  },
];

export const ORGANIZATION_SETTINGS_SECTION_KEYS = ORGANIZATION_SETTINGS_SECTIONS.map(
  (section) => section.key,
);

export const ORGANIZATION_SETTINGS_ICONS = {
  agents: UserRound,
  "spend-limits": Wallet,
  templates: FileCode2,
  skills: Sparkles,
  "memory-access": Brain,
  "organization-memory": Brain,
  "shared-credentials": KeyRound,
  sync: FolderSync,
} as const;

export function visibleOrganizationSettingsSections(canManage: boolean, isMembershipAdmin = canManage) {
  return ORGANIZATION_SETTINGS_SECTIONS.filter(
    (section) =>
      (!section.adminOnly || canManage) && (!section.membershipAdminOnly || isMembershipAdmin),
  );
}
