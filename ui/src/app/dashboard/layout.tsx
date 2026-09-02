"use client";

import { useState } from "react";
import type { ReactNode } from "react";
import { TopNav } from "@/components/top-nav";
import { HireDialog } from "@/features/agents/components/hire-dialog";
import { toast } from "sonner";

export default function DashboardLayout({ children }: { children: ReactNode }) {
  const [hireOpen, setHireOpen] = useState(false);

  return (
    <div className="min-h-screen flex flex-col" style={{ background: "var(--bg)" }}>
      <TopNav onHire={() => setHireOpen(true)} />
      <main className="flex-1">{children}</main>

      {hireOpen && (
        <HireDialog
          onClose={() => setHireOpen(false)}
          onHired={({ name }) => {
            setHireOpen(false);
            toast.success(`${name} was hired successfully.`);
          }}
        />
      )}
    </div>
  );
}
