import { PlatformAdminOnly } from "@/auth/components/platform-admin-only";
import { PlatformTemplatesPage } from "@/features/templates/components/platform-templates-page";

export default function PlatformTemplatesRoute() {
  return (
    <PlatformAdminOnly>
      <PlatformTemplatesPage />
    </PlatformAdminOnly>
  );
}
