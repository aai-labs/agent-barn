"use client";

import { useState } from "react";
import type { ReactNode } from "react";
import { TopNav } from "@/components/top-nav";
import { HireDialog } from "@/features/agents/components/hire-dialog";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";
import { toast } from "sonner";

export default function DashboardLayout({ children }: { children: ReactNode }) {
  const [hireOpen, setHireOpen] = useState(false);
  const { selectedOrganization } = useOrganizationContext();

  return (
    <div className="min-h-screen flex flex-col" style={{ background: "var(--bg)" }}>
      <TopNav onHire={() => setHireOpen(true)} orgName={selectedOrganization?.name} />
      <main className="flex-1 overflow-y-auto">{children}</main>

      {hireOpen && (
        <HireDialog
          onClose={() => setHireOpen(false)}
          onHired={({ name }) => {
            setHireOpen(false);
            toast.success(`${name} is in Slack and ready to roll.`);
          }}
        />
      )}
    </div>
  );
}
