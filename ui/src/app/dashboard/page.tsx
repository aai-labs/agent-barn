"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { AuthLoadingFallback } from "@/auth/components/auth-loading-fallback";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";

/**
 * The dashboard root has no org in its URL. Resolve the active org and redirect into
 * org view. Platform admins with no available org land in Platform View.
 */
export default function DashboardIndexPage() {
  const router = useRouter();
  const { selectedOrganization } = useOrganizationContext();

  useEffect(() => {
    if (selectedOrganization) {
      router.replace(`/dashboard/${selectedOrganization.id}`);
    } else {
      router.replace("/dashboard/platform");
    }
  }, [selectedOrganization, router]);

  return <AuthLoadingFallback message="Loading your workspace…" />;
}
