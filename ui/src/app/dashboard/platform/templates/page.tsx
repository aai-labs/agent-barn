import { PlatformAdminOnly } from "@/auth/components/platform-admin-only";
import { PlatformTemplatesPage } from "@/features/platform-templates/components/platform-templates-page";

export default function PlatformTemplatesRoute() {
  return (
    <PlatformAdminOnly>
      <PlatformTemplatesPage />
    </PlatformAdminOnly>
  );
}
