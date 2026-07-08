import { CostsDashboard } from "@/features/costs/components/costs-dashboard";
import { Metadata } from "next";

export const metadata: Metadata = {
  title: "Costs | Agent Farm",
};

export default function CostsPage() {
  return <CostsDashboard />;
}
