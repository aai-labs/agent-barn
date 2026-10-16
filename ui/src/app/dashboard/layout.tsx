"use client";

import { useState } from "react";
import type { ReactNode } from "react";
import { HireDialog } from "@/features/agents/components/hire-dialog";
import { AppShell } from "@/features/navigation/components/app-shell";
import { NavVariantProvider } from "@/features/navigation/providers/nav-variant-provider";
import { toast } from "sonner";

export default function DashboardLayout({ children }: { children: ReactNode }) {
  const [hireOpen, setHireOpen] = useState(false);

  return (
    <NavVariantProvider>
      <AppShell onHire={() => setHireOpen(true)}>{children}</AppShell>

      {hireOpen && (
        <HireDialog
          onClose={() => setHireOpen(false)}
          onHired={({ name }) => {
            setHireOpen(false);
            toast.success(`${name} was hired successfully.`);
          }}
        />
      )}
    </NavVariantProvider>
  );
}
