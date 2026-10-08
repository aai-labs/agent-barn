import { Metadata } from "next";

import { NoOrganization } from "@/features/onboarding/components/no-organization";

export const metadata: Metadata = { title: "No organization | Agent Barn" };

export default function NoOrganizationPage() {
  return <NoOrganization />;
}
