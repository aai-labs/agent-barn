import { Metadata } from "next";

import { WorkflowsPage } from "@/features/workflows/components/workflows-page";

export const metadata: Metadata = {
  title: "Workflows | Agent Barn",
};

export default async function OrganizationWorkflowsPage({
  params,
}: {
  params: Promise<{ orgId: string }>;
}) {
  const { orgId } = await params;
  return <WorkflowsPage key={orgId} organizationId={orgId} />;
}
