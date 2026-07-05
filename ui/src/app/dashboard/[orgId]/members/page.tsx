import { OrganizationDetail } from "@/features/organizations/components/organization-detail";

export default async function OrganizationMembersPage({
  params,
}: {
  params: Promise<{ orgId: string }>;
}) {
  const { orgId } = await params;
  return <OrganizationDetail organizationId={orgId} />;
}
