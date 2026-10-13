import { Metadata } from "next";

import { PlatformAdminOnly } from "@/auth/components/platform-admin-only";
import { PlatformSettingsPage } from "@/features/platform-settings/components/platform-settings-page";

export const metadata: Metadata = { title: "Platform Settings | Agent Barn" };

export default function PlatformSettingsRoute() {
  return (
    <PlatformAdminOnly>
      <PlatformSettingsPage />
    </PlatformAdminOnly>
  );
}
