"use client";

import { useState } from "react";
import Link from "next/link";
import { Building, Loader2, Lock } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { Badge, type BadgeVariant } from "@/components/badge";
import { ListPageHeader } from "@/components/list-page-header";
import { OrganizationCombobox } from "@/components/organization-combobox";
import { describeSize } from "@/features/agent-sizes/utils";
import { useLoadMoreOnScroll } from "@/hooks/use-load-more-on-scroll";

import { usePlatformAgents } from "../hooks/use-platform-agents";
import type { PlatformAgent } from "../schemas";
import { groupByOrganization } from "../utils";
import { OverrideAgentSizeDialog } from "./override-agent-size-dialog";

const STATUS_VARIANTS: Record<string, BadgeVariant> = { RUNNING: "ok", ERROR: "danger" };

const RUNTIME_LABELS: Record<string, string> = { OPENCLAW: "OpenClaw", HERMES: "Hermes" };

/**
 * Platform → Agents: every live Agent, grouped by Organization, with the CPU and memory each
 * runs on. A Platform Administrator overrides one Agent's size from here.
 *
 * Platform Oversight Data only: no link into an Organization's Agent pages, which a Platform
 * Administrator without a Membership cannot open.
 */
export function PlatformAgentsPage() {
  const [search, setSearch] = useState("");
  const [organization, setOrganization] = useState<{ id: string; name: string } | null>(null);
  // Each opening gets a fresh dialog, keyed on this count.
  const [overriding, setOverriding] = useState<{ agent: PlatformAgent; opening: number } | null>(null);
  const { agents, total, hasNextPage, fetchNextPage, isFetchingNextPage, isLoading, error, refetch } =
    usePlatformAgents({ search, organizationId: organization?.id ?? null });
  const loadMoreRef = useLoadMoreOnScroll({
    hasNextPage: Boolean(hasNextPage),
    isFetchingNextPage,
    fetchNextPage: () => void fetchNextPage(),
  });

  const open = (agent: PlatformAgent) =>
    setOverriding((current) => ({ agent, opening: (current?.opening ?? 0) + 1 }));

  return (
    <div data-testid="platform-agents-page">
      <ListPageHeader
        title="Agents"
        description="Every agent on the platform, by organization, with the CPU and memory it runs on."
        count={total}
        noun="agent"
        onSearch={setSearch}
        searchPlaceholder="Search by agent or organization"
        action={
          <OrganizationCombobox
            organizationId={organization?.id ?? null}
            organizationName={organization?.name ?? null}
            onChange={setOrganization}
          />
        }
      />

      {isLoading ? (
        <p className="m-0 text-[13.5px]" style={{ color: "var(--ink-3)" }}>
          Loading agents…
        </p>
      ) : error ? (
        <AppErrorState
          error={error}
          title="We couldn't load agents"
          description="The platform's agents are unavailable right now."
          onRetry={() => void refetch()}
          retryLabel="Retry"
          className="min-h-[240px] p-0"
        />
      ) : agents.length === 0 ? (
        <div
          className="flex flex-col items-center justify-center rounded-2xl py-16 text-center"
          style={{ border: "1px dashed var(--line-strong)" }}
        >
          <div className="mb-1 text-[15px] font-medium" style={{ color: "var(--ink)" }}>
            No agents found
          </div>
          <div className="text-[13.5px]" style={{ color: "var(--ink-3)" }}>
            Try a different search or organization.
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-5">
          {groupByOrganization(agents).map((group) => (
            <section
              key={group.organizationId}
              className="af-card overflow-x-auto p-0"
              data-testid={`platform-agents-org-${group.organizationId}`}
              aria-label={group.organizationName}
            >
              <div
                className="flex items-center gap-2 px-4 py-3"
                style={{ borderBottom: "1px solid var(--line)" }}
              >
                <Building size={14} style={{ color: "var(--ink-4)", flexShrink: 0 }} />
                <Link
                  href={`/dashboard/platform/organizations/${group.organizationId}`}
                  className="truncate text-[14.5px] font-semibold hover:underline"
                  style={{ color: "var(--ink)" }}
                >
                  {group.organizationName}
                </Link>
                <span className="text-[12.5px]" style={{ color: "var(--ink-4)" }}>
                  {group.agents.length} {group.agents.length === 1 ? "agent" : "agents"}
                </span>
              </div>
              {/* Fixed columns, so every Organization's table lines up with the others. */}
              <table className="w-full min-w-[44rem] table-fixed border-collapse text-[0.84rem]">
                <colgroup>
                  <col className="w-[26%]" />
                  <col className="w-[13%]" />
                  <col className="w-[13%]" />
                  <col className="w-[34%]" />
                  <col className="w-[14%]" />
                </colgroup>
                <thead>
                  <tr className="text-left text-[0.75rem]" style={{ color: "var(--ink-4)" }}>
                    <th className="px-4 py-2.5 font-medium">Agent</th>
                    <th className="px-4 py-2.5 font-medium">Runtime</th>
                    <th className="px-4 py-2.5 font-medium">Status</th>
                    <th className="px-4 py-2.5 font-medium">CPU &amp; memory</th>
                    <th className="px-4 py-2.5" aria-label="Actions" />
                  </tr>
                </thead>
                <tbody>
                  {group.agents.map((agent) => (
                    <AgentRow key={agent.id} agent={agent} onOverride={() => open(agent)} />
                  ))}
                </tbody>
              </table>
            </section>
          ))}
          {hasNextPage && (
            <div
              ref={loadMoreRef}
              className="flex items-center justify-center gap-2 py-6 text-[13px]"
              style={{ color: "var(--ink-4)" }}
            >
              <Loader2 width={14} className={isFetchingNextPage ? "animate-spin" : "invisible"} />
              Loading more agents…
            </div>
          )}
        </div>
      )}

      {overriding && (
        <OverrideAgentSizeDialog
          key={overriding.opening}
          agent={overriding.agent}
          open
          onOpenChange={(isOpen) => !isOpen && setOverriding(null)}
        />
      )}
    </div>
  );
}

function AgentRow({ agent, onOverride }: { agent: PlatformAgent; onOverride: () => void }) {
  return (
    <tr data-testid={`platform-agent-row-${agent.id}`} style={{ borderTop: "1px solid var(--line)" }}>
      <td className="px-4 py-3 font-medium" style={{ color: "var(--ink)" }}>
        {agent.name}
      </td>
      <td className="px-4 py-3" style={{ color: "var(--ink-3)" }}>
        {RUNTIME_LABELS[agent.agentType] ?? agent.agentType}
      </td>
      <td className="px-4 py-3">
        <Badge variant={STATUS_VARIANTS[agent.status] ?? "neutral"}>{agent.status.toLowerCase()}</Badge>
      </td>
      <td className="px-4 py-3">
        <div className="flex flex-wrap items-center gap-1.5" style={{ color: "var(--ink-2)" }}>
          <span data-testid="platform-agent-size">{describeSize(agent.agentSize)}</span>
          {agent.agentSizeId === null && (
            <span className="text-[0.78rem]" style={{ color: "var(--ink-4)" }}>
              (default)
            </span>
          )}
          {agent.agentSizeSetByPlatform && (
            <Badge variant="accent" title="Set by a platform administrator; the organization can't change it">
              <Lock size={10} /> Set by platform
            </Badge>
          )}
        </div>
        {agent.pendingSize && (
          <div className="mt-0.5 text-[0.72rem]" style={{ color: "var(--ink-4)" }}>
            Pending: applies on restart
          </div>
        )}
      </td>
      <td className="px-4 py-3 text-right">
        <button type="button" className="af-btn af-btn-sm" onClick={onOverride} aria-label={`Override size of ${agent.name}`}>
          Override size
        </button>
      </td>
    </tr>
  );
}
