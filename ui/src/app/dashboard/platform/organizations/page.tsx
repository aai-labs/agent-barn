import { PlatformAdminOnly } from "@/auth/components/platform-admin-only";
import { OrganizationsGrid } from "@/features/organizations/components/organizations-grid";

export default function PlatformOrganizationsPage() {
  return (
    <PlatformAdminOnly>
      <OrganizationsGrid />
    </PlatformAdminOnly>
  );
}
