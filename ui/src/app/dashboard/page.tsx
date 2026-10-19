"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { AuthLoadingFallback } from "@/auth/components/auth-loading-fallback";
import { useCurrentUser } from "@/auth/providers/user-context-provider";
import { NoOrganization } from "@/features/onboarding/components/no-organization";
import { useOnboarding } from "@/features/onboarding/hooks/use-onboarding";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";

/**
 * The dashboard root has no org in its URL. Resolve the active org and redirect into
 * org view. Platform admins with no available org land in Platform View; anyone else
 * without one sees a read-only access message. A self-signed-up user who has
 * not finished onboarding goes back to it.
 */
export default function DashboardIndexPage() {
  const router = useRouter();
  const { user } = useCurrentUser();
  const { selectedOrganization } = useOrganizationContext();
  const signedUp = Boolean(user.signedUpAt);
  const { onboarding, isLoadingOnboarding } = useOnboarding({ enabled: signedUp });

  useEffect(() => {
    // An onboarding check that fails never keeps anyone out of the dashboard.
    if (isLoadingOnboarding) return;
    if (onboarding?.required) {
      router.replace("/onboarding");
    } else if (selectedOrganization) {
      router.replace(`/dashboard/${selectedOrganization.id}`);
    } else if (user.isPlatformAdmin) {
      router.replace("/dashboard/platform");
    }
  }, [isLoadingOnboarding, onboarding?.required, selectedOrganization, user.isPlatformAdmin, router]);

  if (!isLoadingOnboarding && !onboarding?.required && !selectedOrganization && !user.isPlatformAdmin) {
    return <NoOrganization />;
  }
  return <AuthLoadingFallback message="Loading your workspace…" />;
}
