import { Metadata } from "next";

import { PlatformAdminOnly } from "@/auth/components/platform-admin-only";
import { PlatformResourceUsagePage } from "@/features/resource-usage/components/platform-resource-usage-page";

export const metadata: Metadata = { title: "Agent Resource Usage | Agent Barn" };

export default function AgentResourceUsageRoute() {
  return (
    <PlatformAdminOnly>
      <PlatformResourceUsagePage agentsOnly />
    </PlatformAdminOnly>
  );
}
