import { Metadata } from "next";

import { OrganizationTasksPage } from "@/features/tasks/components/organization-tasks-page";

export const metadata: Metadata = {
  title: "Tasks | Agent Barn",
};

export default function OrganizationTasksRoute() {
  return <OrganizationTasksPage />;
}
