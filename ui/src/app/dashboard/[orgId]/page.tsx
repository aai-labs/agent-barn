"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { toast } from "sonner";

import { AppErrorState } from "@/components/app-error-state";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useCurrentUser } from "@/auth/providers/user-context-provider";
import { useAgents } from "@/features/agents/hooks/use-agents";
import { AgentCard } from "@/features/agents/components/agent-card";
import { HireDialog } from "@/features/agents/components/hire-dialog";
import { HireTeammateCard } from "@/features/agents/components/hire-teammate-card";
import { isQuiet } from "@/features/agents/utils";

function LoadingCard() {
  return (
    <div className="af-card flex min-h-48 flex-col overflow-hidden" aria-hidden="true">
      <div className="flex items-center gap-3 p-4.5">
        <Skeleton className="size-11 rounded-full" />
        <div className="flex flex-1 flex-col gap-2">
          <Skeleton className="h-4 w-32" />
          <Skeleton className="h-3 w-24" />
        </div>
      </div>
      <div className="flex flex-col gap-2 px-4.5 pb-4">
        <Skeleton className="h-3 w-28" />
        <Skeleton className="h-3 w-36" />
      </div>
      <div className="mt-auto px-4.5 py-3" style={{ background: "var(--bg)", borderTop: "1px solid var(--line)" }}>
        <Skeleton className="h-4 w-28" />
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const params = useParams();
  const orgId = typeof params?.orgId === "string" ? params.orgId : "";
  const [hireOpen, setHireOpen] = useState(false);
  const [search, setSearch] = useState("");
  const { user } = useCurrentUser();
  const { agents, total, isLoading, error, refetch } = useAgents();

  const hour = new Date().getHours();
  const greet = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
  const firstName = (user.fullName ?? user.email ?? "").split(" ")[0];
  const running = agents.filter((a) => a.status === "RUNNING").length;
  const idle = agents.filter((a) => a.status === "STOPPED").length;
  const quiet = agents.filter((a) => a.status !== "STOPPED" && isQuiet(a.lastActivityAt)).length;
  const displayedAgents = agents.filter((agent) => agent.name.toLowerCase().includes(search.trim().toLowerCase()));

  return (
    <div className="af-page">
      <div className="mb-8 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-4xl font-medium tracking-[-0.028em] leading-[1.18] m-0 mb-3" style={{ color: "var(--ink)" }}>
            {greet}, {firstName}
          </h1>
          <div className="text-[0.906rem]" style={{ color: "var(--ink-3)" }}>
            {isLoading ? "Loading…" : `${running} working now · ${idle} idle`}
            {!isLoading && quiet > 0 && <span style={{ color: "var(--warn)" }}> · {quiet} quiet for 2+ weeks</span>}
          </div>
        </div>
      </div>

      <div className="mb-12">
        <div className="mb-5 flex flex-wrap items-center justify-between gap-3 pb-4" style={{ borderBottom: "1px solid var(--line)" }}>
          <h2 className="text-lg font-semibold tracking-tight m-0" style={{ color: "var(--ink)" }}>Your team</h2>
          {!isLoading && !error && agents.length > 0 && (
            <Input className="w-48" type="search" aria-label="Search displayed teammates" placeholder="Search teammates…" value={search} onChange={(event) => setSearch(event.target.value)} />
          )}
        </div>
        {total > agents.length && !isLoading && !error && (
          <p className="mb-4 text-xs" style={{ color: "var(--ink-3)" }}>
            Showing {agents.length} of {total} teammates. Search applies to the teammates shown.
          </p>
        )}

        {error ? (
          <AppErrorState error={error} title="We couldn't load your agents" description="The agents list is unavailable right now." onRetry={() => { void refetch(); }} retryLabel="Retry" className="min-h-60 p-0" />
        ) : (
          <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(min(100%, 18rem), 1fr))" }}>
            {isLoading
              ? Array.from({ length: 3 }).map((_, i) => <LoadingCard key={i} />)
              : displayedAgents.map((agent) => (
                  <AgentCard key={agent.id} agent={agent} href={`/dashboard/${orgId}/agents/${agent.id}`} />
                ))}
            {!isLoading && displayedAgents.length === 0 && (
              <div className="col-span-full flex min-h-56 flex-col items-center justify-center gap-1 text-center" style={{ color: "var(--ink-3)" }}>
                <div className="font-medium text-[0.9375rem]" style={{ color: "var(--ink)" }}>
                  {agents.length === 0 ? "No agents yet" : "No teammates match"}
                </div>
                <div className="text-[0.844rem]">
                  {agents.length === 0 ? "Hire your first teammate to get started." : "Try another name or clear your search."}
                </div>
              </div>
            )}
            {!isLoading && <HireTeammateCard onHire={() => setHireOpen(true)} />}
          </div>
        )}
      </div>

      {hireOpen && (
        <HireDialog onClose={() => setHireOpen(false)} onHired={({ name }) => { setHireOpen(false); toast.success(`${name} was hired successfully.`); }} />
      )}
    </div>
  );
}
