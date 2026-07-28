import { SuperAdminOnly } from "@/auth/components/super-admin-only";
import { UsersGrid } from "@/features/users/components/users-grid";

export default function PlatformUsersPage() {
  return (
    <SuperAdminOnly>
      <UsersGrid />
    </SuperAdminOnly>
  );
}
