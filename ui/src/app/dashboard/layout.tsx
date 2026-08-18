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
      <main className="flex-1 overflow-y-auto">{children}</main>

      {hireOpen && (
        <HireDialog
          onClose={() => setHireOpen(false)}
          onHired={({ name, platform }) => {
            setHireOpen(false);
            toast.success(platform === "discord"
              ? `${name} was hired. Review Discord access, then start the agent.`
              : `${name} is in ${platform === "slack" ? "Slack" : "Telegram"} and ready to roll.`);
          }}
        />
      )}
    </div>
  );
}
