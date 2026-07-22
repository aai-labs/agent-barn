"use client";

import { useCurrentUser } from "@/auth/providers/user-context-provider";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";

/**
 * The current user's role in the active org and whether they can manage it (owner/admin,
 * or a superuser who transcends org roles). Single source for role-gated UI so the check
 * isn't re-derived per component.
 */
export function useActiveOrgRole() {
  const { user, userContext } = useCurrentUser();
  const { selectedOrganization } = useOrganizationContext();

  const role = userContext.organizationUsers?.find(
    (m) => m.organizationId === selectedOrganization?.id,
  )?.role;

  const canManage =
    !!selectedOrganization &&
    (user.isSuperuser || role === "OWNER" || role === "ADMIN");

  return { role, canManage, selectedOrganization };
}
