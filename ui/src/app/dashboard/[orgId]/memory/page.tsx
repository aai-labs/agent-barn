import { Metadata } from "next";

import { OrganizationMemoryPage } from "@/features/agents/components/organization-memory-page";

export const metadata: Metadata = {
  title: "Memory | Agent Barn",
};

export default function MemoryPage() {
  return <OrganizationMemoryPage />;
}
