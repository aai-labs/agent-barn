import { Metadata } from "next";

import { CostsPage } from "@/features/costs/components/costs-page";

export const metadata: Metadata = {
  title: "Costs | Agent Barn",
};

export default function OrganizationCostsPage() {
  return <CostsPage />;
}
