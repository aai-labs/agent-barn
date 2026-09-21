import { createQueryKeyStructure } from "@/shared/query-keys";

export const ORGANIZATIONS_PAGE_SIZE = 12;
export const organizationsKey = createQueryKeyStructure("organizations");
export const platformOrganizationsKey = createQueryKeyStructure("platform-organizations");
// Its own structure rather than a suffix on the detail key: coverage fans out one
// proxy call per Agent, and nesting it meant every budget save re-ran the sweep.
export const organizationLlmCoverageKey = createQueryKeyStructure("organization-llm-coverage");
export const organizationLlmBudgetKey = createQueryKeyStructure("organization-llm-budget");
export const organizationMembersKey = createQueryKeyStructure(
  "organization-members",
);
export const PLATFORM_ORGANIZATION_MEMBERS_PAGE_SIZE = 20;
export const platformOrganizationMembersKey = createQueryKeyStructure(
  "platform-organization-members",
);
