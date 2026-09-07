"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { ChevronRight, Search, X } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";

import { useOrganizationMemory } from "../hooks/use-organization-memory";
import type { OrganizationAgentMemory } from "../schemas";
import { AgentAvatar } from "./agent-avatar";

/** `null` is "we could not ask", `0` is "it knows nothing". Rendering them alike
 *  would invite reading a store outage as an empty agent. */
function describeCount(count: number | null): string {
  if (count === null) return "Unavailable";
  return `${count} ${count === 1 ? "memory" : "memories"}`;
}

export function OrganizationMemoryPage() {
  const { memory, isLoading, error } = useOrganizationMemory();
  const { selectedOrganization } = useOrganizationContext();
  const orgBase = `/dashboard/${selectedOrganization?.id ?? ""}`;
  const [filter, setFilter] = useState("");

  const agents = useMemo(() => {
    const term = filter.trim().toLowerCase();
    if (!term) return memory?.agents ?? [];
    return (memory?.agents ?? []).filter((a) => a.agentName.toLowerCase().includes(term));
  }, [memory?.agents, filter]);

  if (error) {
    return (
      <div className="af-page">
        <Alert variant="destructive">
        <AlertDescription>Could not load memory for this organization. Try again in a moment.</AlertDescription>
        </Alert>
      </div>
    );
  }

  return (
    <div className="af-page space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight" style={{ color: "var(--ink)" }}>
          Memory
        </h1>
        <p className="mt-1 text-sm" style={{ color: "var(--ink-3)" }}>
          What each agent has learned. Deleted agents keep their memory, so they are listed here too.
        </p>
      </div>

      <div className="relative w-full sm:max-w-sm">
        <Search
          size={15}
          aria-hidden
          className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2"
          style={{ color: "var(--ink-4)" }}
        />
        <Input
          placeholder="Filter agents…"
          aria-label="Filter agents by name"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="pl-9"
        />
        {filter.length > 0 && (
          <button
            type="button"
            onClick={() => setFilter("")}
            aria-label="Clear filter"
            className="absolute top-1/2 right-2 -translate-y-1/2 rounded-full p-1 transition-colors duration-150 hover:bg-[var(--bg-sunken)]"
            style={{ color: "var(--ink-4)" }}
          >
            <X size={14} />
          </button>
        )}
      </div>

      {isLoading ? (
        <div
          className="divide-y overflow-hidden rounded-lg"
          style={{ background: "var(--bg-elev)", border: "1px solid var(--line)" }}
        >
          {Array.from({ length: 4 }, (_, i) => (
            <div key={i} className="flex items-center gap-3 px-4 py-3.5">
              <Skeleton className="size-8 shrink-0 rounded-full" />
              <Skeleton className="h-4 w-48" />
            </div>
          ))}
        </div>
      ) : (memory?.agents.length ?? 0) === 0 ? (
        <div
          className="rounded-lg px-6 py-12 text-center"
          style={{ background: "var(--bg-soft)", border: "1px dashed var(--line-strong)" }}
        >
          <p className="text-sm font-medium" style={{ color: "var(--ink-2)" }}>
            No agents yet
          </p>
          <p className="mt-1.5 text-sm" style={{ color: "var(--ink-3)" }}>
            Once an agent has held a conversation, what it learned shows up here.
          </p>
        </div>
      ) : agents.length === 0 ? (
        <div
          className="rounded-lg px-6 py-12 text-center text-sm"
          style={{ background: "var(--bg-soft)", border: "1px dashed var(--line-strong)", color: "var(--ink-3)" }}
        >
          No agents match “{filter}”.
        </div>
      ) : (
        <>
          <p className="text-sm" style={{ color: "var(--ink-3)" }}>
            {memory?.totalMemories.toLocaleString()} {memory?.totalMemories === 1 ? "memory" : "memories"} across{" "}
            {memory?.agents.length} {memory?.agents.length === 1 ? "agent" : "agents"}
            {memory?.partial && " · some agents could not be reached, so the total is a minimum"}
          </p>

          <div
            className="divide-y overflow-hidden rounded-lg"
            style={{ background: "var(--bg-elev)", border: "1px solid var(--line)" }}
          >
            {agents.map((agent: OrganizationAgentMemory) => (
              <Link
                key={agent.agentId}
                href={`${orgBase}/agents/${agent.agentId}?tab=memory`}
                className="flex items-center gap-3 px-4 py-3.5 transition-colors duration-150 hover:bg-[var(--bg-soft)]"
              >
                <AgentAvatar agent={{ id: agent.agentId, name: agent.agentName }} size="sm" />
                <span className="min-w-0 flex-1 truncate text-sm" style={{ color: "var(--ink)" }}>
                  {agent.agentName}
                </span>
                {agent.deleted && (
                  <span
                    className="shrink-0 rounded-full px-2 py-0.5 text-[0.75rem]"
                    style={{ background: "var(--bg-soft)", border: "1px solid var(--line)", color: "var(--ink-3)" }}
                  >
                    Deleted
                  </span>
                )}
                <span
                  className="shrink-0 text-sm tabular-nums"
                  style={{ color: agent.memoryCount === null ? "var(--ink-4)" : "var(--ink-3)" }}
                >
                  {describeCount(agent.memoryCount)}
                </span>
                <ChevronRight size={15} aria-hidden style={{ color: "var(--ink-4)" }} />
              </Link>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
