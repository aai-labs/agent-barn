import { Metadata } from "next";

import { PlatformAdminOnly } from "@/auth/components/platform-admin-only";
import { PlatformMemorySettings } from "@/features/agent-memory/components/platform-memory-settings";

export const metadata: Metadata = { title: "Platform Settings | Agent Barn" };

export default function PlatformSettingsRoute() {
  return <PlatformAdminOnly><PlatformMemorySettings /></PlatformAdminOnly>;
}
