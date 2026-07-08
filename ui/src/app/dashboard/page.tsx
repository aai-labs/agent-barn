"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { AuthLoadingFallback } from "@/auth/components/auth-loading-fallback";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";

/**
 * The dashboard root has no org in its URL. Resolve the active org (the provider falls
 * back to the last-used / default) and redirect into its scoped home. Superusers with no
 * memberships go to the org admin list instead.
 */
export default function DashboardIndexPage() {
  const router = useRouter();
  const { selectedOrganization } = useOrganizationContext();

  useEffect(() => {
    if (selectedOrganization) {
      router.replace(`/dashboard/${selectedOrganization.id}`);
    } else {
      router.replace("/dashboard/organizations");
    }
  }, [selectedOrganization, router]);

  return <AuthLoadingFallback message="Loading your workspace…" />;
}
