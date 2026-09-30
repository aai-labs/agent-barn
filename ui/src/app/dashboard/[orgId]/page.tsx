"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import type { Agent } from "@/features/agents/schemas";
import { useAgents } from "@/features/agents/hooks/use-agents";
import { AgentCard } from "@/features/agents/components/agent-card";
import { HireDialog } from "@/features/agents/components/hire-dialog";
import { AppErrorState } from "@/components/app-error-state";
import { useCurrentUser } from "@/auth/providers/user-context-provider";
import { toast } from "sonner";

function LoadingCard() {
  return (
    <div className="af-card px-5.5 py-5 animate-pulse min-h-[14.375rem] flex flex-col gap-5">
      <div className="flex items-center gap-4">
        <div className="w-14 h-14 rounded-full flex-shrink-0" style={{ background: "var(--bg-soft)" }} />
        <div className="flex-1 flex flex-col gap-2">
          <div className="h-4.5 w-32 rounded-md" style={{ background: "var(--bg-soft)" }} />
          <div className="h-3.5 w-24 rounded-md" style={{ background: "var(--bg-soft)" }} />
        </div>
      </div>
      <div className="flex-1 flex flex-col gap-2">
        <div className="h-3.5 w-20 rounded-md" style={{ background: "var(--bg-soft)" }} />
      </div>
      <div className="flex items-center justify-between pt-3.5" style={{ borderTop: "1px solid var(--line)" }}>
        <div className="h-8 w-16 rounded-lg" style={{ background: "var(--bg-soft)" }} />
        <div className="h-3.5 w-12 rounded-md" style={{ background: "var(--bg-soft)" }} />
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const router = useRouter();
  const params = useParams();
  const orgId = typeof params?.orgId === "string" ? params.orgId : "";
  const [hireOpen, setHireOpen] = useState(false);
  const { user } = useCurrentUser();
  const { agents, isLoading, error, refetch } = useAgents();

  const hour = new Date().getHours();
  const greet = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
  const firstName = (user.fullName ?? user.email ?? "").split(" ")[0];

  const running = agents.filter((a) => a.status === "RUNNING").length;
  const idle = agents.filter((a) => a.status === "STOPPED").length;

  const handleOpen = (agent: Agent) => {
    router.push(`/dashboard/${orgId}/agents/${agent.id}`);
  };

  return (
    <div className="af-page">
      <div className="mb-14">
        <h1 className="text-4xl font-medium tracking-[-0.028em] leading-[1.18] m-0 mb-3" style={{ color: "var(--ink)" }}>
          {greet}, {firstName}
        </h1>
        <div className="text-[0.906rem]" style={{ color: "var(--ink-3)" }}>
          {isLoading ? "Loading…" : `${running} working now · ${idle} idle`}
        </div>
      </div>

      <div className="mb-12">
        <div className="mb-5">
          <h2 className="text-lg font-semibold tracking-tight m-0" style={{ color: "var(--ink)" }}>
            Your team
          </h2>
        </div>

        {error ? (
          <AppErrorState
            error={error}
            title="We couldn't load your agents"
            description="The agents list is unavailable right now."
            onRetry={() => { void refetch(); }}
            retryLabel="Retry"
            className="min-h-[15rem] p-0"
          />
        ) : (
          <div
            className="grid gap-4"
            style={{ gridTemplateColumns: "repeat(auto-fill, minmax(20rem, 1fr))" }}
          >
            {isLoading
              ? Array.from({ length: 3 }).map((_, i) => <LoadingCard key={i} />)
              : agents.map((a) => (
                  <AgentCard key={a.id} agent={a} onOpen={handleOpen} />
                ))}

            {!isLoading && agents.length === 0 && (
              <div
                className="flex flex-col items-center justify-center text-center px-5.5 py-12 rounded-2xl col-span-full"
                style={{ border: "1px dashed var(--line-strong)", color: "var(--ink-3)" }}
              >
                <div className="font-medium text-[0.9375rem] mb-1" style={{ color: "var(--ink)" }}>No agents yet</div>
                <div className="text-[0.844rem]" style={{ color: "var(--ink-3)" }}>
                  Hire your first teammate to get started.
                </div>
              </div>
            )}

            <div
              className="flex flex-col items-center justify-center text-center px-5.5 py-7 rounded-2xl cursor-default min-h-[14.375rem] transition-colors"
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
              <div className="font-semibold text-[0.9375rem] mb-1">Hire a teammate</div>
              <div className="text-[0.8125rem] max-w-[13.75rem] leading-[1.45]" style={{ color: "var(--ink-4)" }}>
                A scrum master, PR reviewer, support rep — ready in a couple of minutes.
              </div>
            </div>
          </div>
        )}
      </div>

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
