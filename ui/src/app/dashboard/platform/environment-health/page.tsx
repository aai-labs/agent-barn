import { Metadata } from "next";

import { PlatformAdminOnly } from "@/auth/components/platform-admin-only";
import { EnvironmentHealthPage } from "@/features/environment-health/components/environment-health-page";

export const metadata: Metadata = {
  title: "Environment Health | Agent Barn",
};

export default function EnvironmentHealthRoute() {
  return (
    <PlatformAdminOnly>
      <EnvironmentHealthPage />
    </PlatformAdminOnly>
  );
}
