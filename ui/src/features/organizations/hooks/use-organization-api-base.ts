"use client";

import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";

export function useOrganizationApiBase(): string {
  const { selectedOrganization } = useOrganizationContext();
  if (!selectedOrganization) {
    throw new Error("No active organization is available for an organization-scoped request");
  }
  return `/api/v1/organizations/${selectedOrganization.id}`;
}
