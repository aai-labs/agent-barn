import { CostsDashboard } from "@/features/costs/components/costs-dashboard";
import { Metadata } from "next";

export const metadata: Metadata = {
  title: "Costs | Agent Barn",
};

export default function CostsPage() {
  return <CostsDashboard />;
}
