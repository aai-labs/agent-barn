export type OrganizationSettingsSectionKey =
  | "agents"
  | "templates"
  | "skills"
  | "organization-memory"
  | "memory-access"
  | "shared-credentials";

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
    label: "Agents",
    description:
      "Defaults every Agent in this organization follows unless it has been given its own setting.",
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
];

export const ORGANIZATION_SETTINGS_SECTION_KEYS = ORGANIZATION_SETTINGS_SECTIONS.map(
  (section) => section.key,
);

export function visibleOrganizationSettingsSections(canManage: boolean, isMembershipAdmin = canManage) {
  return ORGANIZATION_SETTINGS_SECTIONS.filter(
    (section) =>
      (!section.adminOnly || canManage) && (!section.membershipAdminOnly || isMembershipAdmin),
  );
}
