import { Metadata } from "next";

import { PlatformAdminOnly } from "@/auth/components/platform-admin-only";
import { PlatformAgentAddonsPage } from "@/features/agent-addons/components/platform-agent-addons-page";

export const metadata: Metadata = {
  title: "Platform Add-ons | Agent Barn",
};

export default function PlatformAgentAddonsRoute() {
  return (
    <PlatformAdminOnly>
      <PlatformAgentAddonsPage />
    </PlatformAdminOnly>
  );
}
