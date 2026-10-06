import { Metadata } from "next";

import { AgentsOverviewPage } from "@/features/resource-usage/components/agents-overview-page";

export const metadata: Metadata = {
  title: "Usage | Agent Barn",
};

export default function OrganizationAgentsPage() {
  return <AgentsOverviewPage />;
}
