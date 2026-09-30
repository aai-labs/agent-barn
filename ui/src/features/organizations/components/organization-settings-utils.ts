export type OrganizationSettingsSectionKey =
  | "agents"
  | "templates"
  | "skills"
  | "shared-credentials";

export type OrganizationSettingsSection = {
  key: OrganizationSettingsSectionKey;
  label: string;
  /** Rendered under the section heading, so it says what the section is for. */
  description: string;
  /** Hidden from Members entirely, the way Shared Credentials already is. */
  adminOnly: boolean;
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
    key: "shared-credentials",
    label: "Shared Credentials",
    description: "Organization-wide integration keys reusable across Agents.",
    adminOnly: true,
  },
];

export const ORGANIZATION_SETTINGS_SECTION_KEYS = ORGANIZATION_SETTINGS_SECTIONS.map(
  (section) => section.key,
);

export function visibleOrganizationSettingsSections(canManage: boolean) {
  return ORGANIZATION_SETTINGS_SECTIONS.filter((section) => !section.adminOnly || canManage);
}
