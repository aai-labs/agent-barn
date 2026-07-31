import { PlatformAdminOnly } from "@/auth/components/platform-admin-only";
import { PlatformOrganizationDetail } from "@/features/organizations/components/platform-organization-detail";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default async function PlatformOrganizationDetailPage({ params }: PageProps) {
  const { id } = await params;
  return (
    <PlatformAdminOnly>
      <PlatformOrganizationDetail organizationId={id} />
    </PlatformAdminOnly>
  );
}
