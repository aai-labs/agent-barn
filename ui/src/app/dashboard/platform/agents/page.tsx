import { Metadata } from "next";

import { PlatformAdminOnly } from "@/auth/components/platform-admin-only";
import { PlatformAgentsPage } from "@/features/platform-agents/components/platform-agents-page";

export const metadata: Metadata = {
  title: "Platform Agents | Agent Barn",
};

export default function PlatformAgentsRoute() {
  return (
    <PlatformAdminOnly>
      <PlatformAgentsPage />
    </PlatformAdminOnly>
  );
}
