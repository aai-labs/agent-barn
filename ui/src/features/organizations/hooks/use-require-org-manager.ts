"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { useActiveOrgRole } from "./use-active-org-role";

/**
 * Guards an owner/admin-only page. A member who lands on it — e.g. by switching orgs while
 * viewing it (the switcher preserves the sub-page), which the API would answer with 403 —
 * is redirected to that org's dashboard home instead of hitting a dead-end with no nav out.
 * Returns whether the user may view the page, so callers can render nothing meanwhile.
 */
export function useRequireOrgManager(): boolean {
  const router = useRouter();
  const { canManage, selectedOrganization } = useActiveOrgRole();

  useEffect(() => {
    if (selectedOrganization && !canManage) {
      router.replace(`/dashboard/${selectedOrganization.id}`);
    }
  }, [canManage, selectedOrganization, router]);

  return canManage;
}
