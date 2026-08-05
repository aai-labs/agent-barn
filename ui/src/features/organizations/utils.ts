import { createQueryKeyStructure } from "@/shared/query-keys";

export const ORGANIZATIONS_PAGE_SIZE = 12;
export const organizationsKey = createQueryKeyStructure("organizations");
export const platformOrganizationsKey = createQueryKeyStructure("platform-organizations");
export const organizationMembersKey = createQueryKeyStructure(
  "organization-members",
);
export const PLATFORM_ORGANIZATION_MEMBERS_PAGE_SIZE = 20;
export const platformOrganizationMembersKey = createQueryKeyStructure(
  "platform-organization-members",
);
