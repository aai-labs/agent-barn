"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { AGENTS } from "@/features/agents/data";
import type { Agent } from "@/features/agents/types";
import { AgentCard } from "@/features/agents/components/agent-card";
import { HireDialog } from "@/features/agents/components/hire-dialog";
import { useCurrentUser } from "@/auth/providers/user-context-provider";
import { toast } from "sonner";

export default function DashboardPage() {
  const router = useRouter();
  const [hireOpen, setHireOpen] = useState(false);
  const { user } = useCurrentUser();

  const hour = new Date().getHours();
  const greet = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
  const firstName = (user.fullName ?? user.email ?? "").split(" ")[0];

  const running = AGENTS.filter((a) => a.status === "RUNNING").length;
  const idle = AGENTS.filter((a) => a.status === "STOPPED").length;

  const handleOpen = (agent: Agent) => {
    router.push(`/dashboard/agents/${agent.id}`);
  };

  return (
    <div className="max-w-[1200px] mx-auto px-10 pt-9 pb-24">
      <div className="mb-14">
        <h1 className="text-[36px] font-medium tracking-[-0.028em] leading-[1.18] m-0 mb-3" style={{ color: "var(--ink)" }}>
          {greet}, {firstName}
        </h1>
        <div className="text-[14.5px]" style={{ color: "var(--ink-3)" }}>
          {running} working now · {idle} idle
        </div>
      </div>

      <div className="mb-12">
        <div className="mb-5">
          <h2 className="text-[18px] font-semibold tracking-tight m-0" style={{ color: "var(--ink)" }}>
            Your team
          </h2>
        </div>

        <div
          className="grid gap-4"
          style={{ gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))" }}
        >
          {AGENTS.map((a) => (
            <AgentCard key={a.id} agent={a} onOpen={handleOpen} />
          ))}
          <div
            className="flex flex-col items-center justify-center text-center px-[22px] py-7 rounded-2xl cursor-default min-h-[230px] transition-colors"
            style={{ border: "1px dashed var(--line-strong)", color: "var(--ink-3)" }}
            onClick={() => setHireOpen(true)}
            onMouseEnter={(e) => {
              const el = e.currentTarget as HTMLElement;
              el.style.background = "var(--bg-soft)";
              el.style.borderColor = "var(--ink-3)";
              el.style.color = "var(--ink)";
            }}
            onMouseLeave={(e) => {
              const el = e.currentTarget as HTMLElement;
              el.style.background = "transparent";
              el.style.borderColor = "var(--line-strong)";
              el.style.color = "var(--ink-3)";
            }}
          >
            <div
              className="w-11 h-11 rounded-full grid place-items-center text-xl mb-3.5"
              style={{ background: "var(--bg-elev)", border: "1px solid var(--line)", color: "var(--ink-2)" }}
            >
              +
            </div>
            <div className="font-semibold text-[15px] mb-1">Hire a teammate</div>
            <div className="text-[13px] max-w-[220px] leading-[1.45]" style={{ color: "var(--ink-4)" }}>
              A scrum master, PR reviewer, support rep — ready in a couple of minutes.
            </div>
          </div>
        </div>
      </div>

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
