import { SuperAdminOnly } from "@/auth/components/super-admin-only";
import { OrganizationsGrid } from "@/features/organizations/components/organizations-grid";

export default function PlatformOrganizationsPage() {
  return (
    <SuperAdminOnly>
      <OrganizationsGrid />
    </SuperAdminOnly>
  );
}
