import { Metadata } from "next";

import { PlatformAdminOnly } from "@/auth/components/platform-admin-only";
import { PlatformCostsPage } from "@/features/costs/components/platform-costs-page";

export const metadata: Metadata = {
  title: "Platform Costs | Agent Barn",
};

export default function PlatformCostsRoute() {
  return (
    <PlatformAdminOnly>
      <PlatformCostsPage />
    </PlatformAdminOnly>
  );
}
