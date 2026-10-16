"use client";

import { usePathname, useRouter } from "next/navigation";

import { useCurrentUser } from "@/auth/providers/user-context-provider";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";

import type { Organization } from "../schemas";

// Segments directly under /dashboard/ that are NOT an org id (global admin / personal).
const GLOBAL_DASHBOARD_SEGMENTS = new Set(["account", "platform"]);

/**
 * Moving between Organizations and Platform View, for every switcher that offers it.
 */
export function useOrganizationSwitch() {
  const { organizations, selectedOrganization } = useOrganizationContext();
  const { user } = useCurrentUser();
  const router = useRouter();
  const pathname = usePathname() ?? "";
  const isPlatformView = pathname.startsWith("/dashboard/platform");
  // Mirrors the API: a self-signed-up user stays on their trial (even after deleting
  // it) until a platform admin ends it, and nobody owning a running trial creates more.
  const onTrial =
    (Boolean(user.signedUpAt) && !user.trialEndedAt) ||
    (user.organizationUsers ?? []).some(
      (membership) => membership.role === "OWNER" && membership.organization.isTrial,
    );

  const selectOrganization = (org: Organization) => {
    if (!isPlatformView && org.id === selectedOrganization?.id) return;

    // Stay on the same sub-page under the new org by swapping the org segment; from a
    // global page (no org in the URL) land on the new org's home.
    const parts = pathname.split("/"); // ["", "dashboard", <seg>, ...]
    const isOrgScopedRoute =
      parts[1] === "dashboard" &&
      !!parts[2] &&
      !GLOBAL_DASHBOARD_SEGMENTS.has(parts[2]);

    if (isOrgScopedRoute) {
      parts[2] = org.id;
      router.push(parts.join("/"));
    } else {
      router.push(`/dashboard/${org.id}`);
    }
  };

  const selectPlatform = () => {
    if (!isPlatformView) {
      router.push("/dashboard/platform");
    }
  };

  return {
    organizations,
    selectedOrganization,
    isPlatformView,
    isPlatformAdmin: user.isPlatformAdmin,
    canCreateOrganization: !onTrial,
    selectOrganization,
    selectPlatform,
  };
}
