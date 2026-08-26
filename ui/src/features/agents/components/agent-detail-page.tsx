"use client";

import { useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useQueryState, parseAsStringEnum, parseAsString } from "nuqs";
import { MessageCircleWarning, Plus } from "lucide-react";
import { canAgent, currentModelOf, formatModelName } from "../utils";
import { ModelSourceBadge } from "./model-source-badge";
import { PendingModelNote } from "./pending-model-note";
import { useAgent } from "../hooks/use-agent";
import { useAgentHealth } from "../hooks/use-agent-health";
import { useStartAgent } from "../hooks/use-start-agent";
import { useStopAgent } from "../hooks/use-stop-agent";
import { useCommunicationConnections } from "@/features/communication-connections/hooks/use-communication-connections";
import {
  ChevLeftIcon,
  PauseIcon,
  PlayIcon,
  CogIcon,
  ShareIcon,
} from "@/components/icons";
import { AppErrorState } from "@/components/app-error-state";
import { toastError } from "@/shared/toast";
import { AgentAvatar } from "./agent-avatar";
import { AgentMetaBadges } from "./agent-meta-badges";
import { StatusLine } from "./status-line";
import { ConversationsTab } from "./conversations-tab";
import { ToolCallsTab } from "./tool-calls-tab";
import { LogsTab } from "./logs-tab";
import { WorkTab } from "./work-tab";
import { AboutTab } from "./about-tab";
import { ShareDialog } from "./share-dialog";
import { AgentDetailHeaderSkeleton } from "./agent-detail-header-skeleton";

interface AgentDetailPageProps {
  agentId: string;
}

type Tab = "conversations" | "tool-calls" | "logs" | "work" | "about";
const VALID_TABS: Tab[] = [
  "conversations",
  "tool-calls",
  "logs",
  "work",
  "about",
];

export function AgentDetailPage({ agentId }: AgentDetailPageProps) {
  const { agent, isLoading, error, refetch } = useAgent(agentId);
  const canReadActivity = canAgent(agent, "activity.read");
  const { health } = useAgentHealth(
    agentId,
    canReadActivity &&
      (agent?.status === "RUNNING" || agent?.status === "ERROR"),
  );
  const stopAgent = useStopAgent();
  const startAgent = useStartAgent();
  const [tab, setTab] = useQueryState(
    "tab",
    parseAsStringEnum<Tab>(VALID_TABS)
      .withDefault("conversations")
      .withOptions({ scroll: false, history: "replace" }),
  );
  const [, setChannel] = useQueryState(
    "channel",
    parseAsString.withOptions({ history: "replace" }),
  );

  function selectTab(next: Tab) {
    void setTab(next);
    // channel is only meaningful on the conversations tab; drop it elsewhere
    if (next !== "conversations") void setChannel(null);
  }

  const tabs: [Tab, string][] = [
    ...(canReadActivity
      ? ([
          ["conversations", "Conversations"],
          ["tool-calls", "Tool calls"],
          ["logs", "Logs"],
          ["work", "Work"],
        ] as [Tab, string][])
      : []),
    ["about", "About"],
  ];
  const resolvedTab = tabs.some(([key]) => key === tab) ? tab : tabs[0][0];

  const isRunning = agent?.status === "RUNNING";
  const canManageLifecycle = canAgent(agent, "agent.lifecycle.manage");
  const canManageAccess = canAgent(agent, "agent.access.manage");
  const canManageConnections = canAgent(agent, "agent.update");
  const connections = useCommunicationConnections(agent?.id ?? "");
  const isUnreachable =
    !connections.isPending && connections.data?.length === 0;
  const [shareOpen, setShareOpen] = useState(false);

  const params = useParams();
  const orgId = typeof params?.orgId === "string" ? params.orgId : null;
  const homeHref = orgId ? `/dashboard/${orgId}` : "/dashboard";

  return (
    <div style={{ background: "var(--bg)" }}>
      <div className="af-page">
        <Link
          href={homeHref}
          className="inline-flex items-center gap-1.5 text-[0.8125rem] mb-6 px-2 py-1 -ml-2 rounded-lg hover:bg-[var(--bg-soft)] transition-colors"
          style={{ color: "var(--ink-3)" }}
        >
          <ChevLeftIcon />
          Your team
        </Link>

        {isLoading && <AgentDetailHeaderSkeleton />}

        {error && (
          <AppErrorState
            error={error}
            title="We couldn't load this agent"
            description="The agent may have been deleted or is unavailable."
            onRetry={() => {
              void refetch();
            }}
            retryLabel="Retry"
            className="min-h-[15rem] p-0"
          />
        )}

        {agent && (
          <>
            <div className="flex items-start gap-5.5 pb-8">
              <AgentAvatar agent={agent} size="xl" />
              <div className="flex-1 min-w-0">
                <h1
                  className="text-[2.5rem] font-semibold tracking-[-0.028em] m-0 mb-1 leading-[1.1]"
                  style={{ color: "var(--ink)" }}
                >
                  {agent.name}
                </h1>
                {currentModelOf(agent) && (
                  <>
                    <div className="flex items-center gap-2 text-[0.906rem]" style={{ color: "var(--ink-3)" }}>
                      <span className="font-mono">{formatModelName(currentModelOf(agent))}</span>
                      <ModelSourceBadge source={agent.modelSource} />
                    </div>
                    <PendingModelNote pendingModel={agent.pendingModel} />
                  </>
                )}
                <AgentMetaBadges
                  agent={agent}
                  variant="full"
                  className="mt-2"
                />
                <div className="mt-2">
                  <StatusLine status={agent.status} health={health} />
                </div>
              </div>
              <div className="flex gap-2">
                {isRunning && canManageLifecycle && (
                  <button
                    className="af-btn"
                    disabled={stopAgent.isPending}
                    onClick={() => {
                      void stopAgent.mutateAsync(agent.id).catch(toastError);
                    }}
                  >
                    <PauseIcon /> {stopAgent.isPending ? "Pausing…" : "Pause"}
                  </button>
                )}
                {!isRunning && canManageLifecycle && (
                  <button
                    className="af-btn"
                    disabled={startAgent.isPending}
                    onClick={() => {
                      void startAgent.mutateAsync(agent.id).catch(toastError);
                    }}
                  >
                    <PlayIcon /> {startAgent.isPending ? "Starting…" : "Start"}
                  </button>
                )}
                <Link
                  href={`${homeHref}/agents/${agent.id}/configuration`}
                  className="af-btn"
                >
                  <CogIcon /> Configuration
                </Link>
                {canManageAccess && (
                  <button className="af-btn" onClick={() => setShareOpen(true)}>
                    <ShareIcon /> Share
                  </button>
                )}
              </div>
            </div>

            {(agent.status === "ERROR" ||
              health?.status === "crashed" ||
              health?.status === "error") &&
              health?.reason && (
                <div
                  className="mb-6 rounded-xl px-4 py-3 text-[0.844rem]"
                  style={{
                    background:
                      "color-mix(in srgb, var(--err) 10%, transparent)",
                    border:
                      "1px solid color-mix(in srgb, var(--err) 25%, transparent)",
                    color: "var(--err)",
                  }}
                >
                  <span className="font-medium">Error: </span>
                  {health.reason}
                </div>
              )}

            {isUnreachable && (
              <div
                className="mb-6 overflow-hidden rounded-2xl"
                style={{
                  border:
                    "1px solid color-mix(in srgb, var(--warn) 30%, var(--line))",
                  background: "var(--warn-soft)",
                }}
              >
                <div className="flex flex-col gap-4 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex min-w-0 items-start gap-3.5">
                    <span
                      className="grid h-10 w-10 flex-shrink-0 place-items-center rounded-xl"
                      style={{
                        background:
                          "color-mix(in srgb, var(--warn) 16%, transparent)",
                        color: "var(--warn)",
                      }}
                    >
                      <MessageCircleWarning size={19} />
                    </span>
                    <div className="min-w-0">
                      <div className="mb-1 flex flex-wrap items-center gap-2">
                        <span
                          className="text-[0.6875rem] font-semibold uppercase tracking-[0.1em]"
                          style={{ color: "var(--warn)" }}
                        >
                          Messaging setup
                        </span>
                        <span
                          className="rounded-full px-2 py-0.5 text-[0.6875rem] font-medium"
                          style={{
                            border:
                              "1px solid color-mix(in srgb, var(--warn) 28%, transparent)",
                            color: "var(--warn)",
                          }}
                        >
                          Not connected
                        </span>
                      </div>
                      <div
                        className="text-[0.95rem] font-semibold"
                        style={{ color: "var(--ink)" }}
                      >
                        Make {agent.name} reachable
                      </div>
                      <p
                        className="mb-0 mt-1 text-[0.844rem] leading-relaxed"
                        style={{ color: "var(--ink-3)" }}
                      >
                        Connect a messaging platform so people can message this
                        Agent.
                      </p>
                    </div>
                  </div>
                  {canManageConnections && (
                    <Link
                      href={`${homeHref}/agents/${agent.id}/configuration?section=channels&connect=true`}
                      className="af-btn af-btn-primary af-btn-sm flex-shrink-0 self-start sm:self-auto"
                    >
                      <Plus size={14} /> Add connection
                    </Link>
                  )}
                </div>
              </div>
            )}

            <div
              className="flex items-center gap-1 mb-7"
              style={{ borderBottom: "1px solid var(--line)" }}
            >
              {tabs.map(([k, l]) => (
                <button
                  key={k}
                  className="ap-tab"
                  data-active={resolvedTab === k}
                  onClick={() => {
                    selectTab(k);
                  }}
                >
                  {l}
                </button>
              ))}
            </div>

            {resolvedTab === "conversations" && (
              <ConversationsTab agent={agent} />
            )}
            {resolvedTab === "tool-calls" && <ToolCallsTab agent={agent} />}
            {resolvedTab === "logs" && <LogsTab agent={agent} />}
            {resolvedTab === "work" && <WorkTab agent={agent} />}
            {resolvedTab === "about" && <AboutTab />}
          </>
        )}
      </div>

      {agent && canManageAccess && (
        <ShareDialog
          agentId={agent.id}
          agentName={agent.name}
          organizationId={agent.organizationId}
          open={shareOpen}
          onOpenChange={setShareOpen}
        />
      )}
    </div>
  );
}
