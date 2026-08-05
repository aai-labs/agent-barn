import { PlatformAdminOnly } from "@/auth/components/platform-admin-only";
import { UserDetail } from "@/features/users/components/user-detail";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default async function PlatformUserDetailPage({ params }: PageProps) {
  const { id } = await params;
  return (
    <PlatformAdminOnly>
      <UserDetail userId={id} />
    </PlatformAdminOnly>
  );
}
