import { Metadata } from "next";

import { PlatformAdminOnly } from "@/auth/components/platform-admin-only";
import { PlatformSettings } from "@/features/platform-settings/components/platform-settings";

export const metadata: Metadata = { title: "Platform Settings | Agent Barn" };

export default function PlatformSettingsRoute() {
  return (
    <PlatformAdminOnly>
      <PlatformSettings />
    </PlatformAdminOnly>
  );
}
