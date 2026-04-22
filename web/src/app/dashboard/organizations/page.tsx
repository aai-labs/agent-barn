import { SuperAdminOnly } from "@/auth/components/super-admin-only";
import { OrganizationsGrid } from "@/organizations/components/organizations-grid";

export default function OrganizationsPage() {
  return (
    <SuperAdminOnly>
      <OrganizationsGrid />
    </SuperAdminOnly>
  );
}
