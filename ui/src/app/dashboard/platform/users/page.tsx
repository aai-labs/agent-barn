import { PlatformAdminOnly } from "@/auth/components/platform-admin-only";
import { UsersGrid } from "@/features/users/components/users-grid";

export default function PlatformUsersPage() {
  return (
    <PlatformAdminOnly>
      <UsersGrid />
    </PlatformAdminOnly>
  );
}
