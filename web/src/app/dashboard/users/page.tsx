import { SuperAdminOnly } from "@/auth/components/super-admin-only";
import { UsersGrid } from "@/features/users/components/users-grid";

export default function UsersPage() {
  return (
    <SuperAdminOnly>
      <UsersGrid />
    </SuperAdminOnly>
  );
}
