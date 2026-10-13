import { Metadata } from "next";

import { KpisPage } from "@/features/business-value/components/kpis-page";

export const metadata: Metadata = {
  title: "KPIs | Agent Barn",
};

export default function OrganizationKpisPage() {
  return <KpisPage />;
}
