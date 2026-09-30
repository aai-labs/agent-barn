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
import { useCommunicationConnections } from "@/features/communication-connections/hooks/use-communication-connections";
import { ChevLeftIcon, CogIcon, ShareIcon } from "@/components/icons";
import { AppErrorState } from "@/components/app-error-state";
import { AgentCostsPanel } from "@/features/costs/components/agent-costs-panel";
import { AgentAvatar } from "./agent-avatar";
import { AgentErrorBanner, AgentHealthErrorBanner } from "./agent-error-banner";
import { AgentLifecycleMenu } from "./agent-lifecycle-menu";
import { AgentMetaBadges } from "./agent-meta-badges";
import { AgentUpdateBanner } from "./agent-update-banner";
import { StatusLine } from "./status-line";
import { ChatTab } from "./chat-tab";
import { ConversationsTab } from "./conversations-tab";
import { ToolCallsTab } from "./tool-calls-tab";
import { LogsTab } from "./logs-tab";
import { ActivityTab } from "./activity-tab";
import { AboutTab } from "./about-tab";
import { ShareDialog } from "./share-dialog";
import { AgentDetailHeaderSkeleton } from "./agent-detail-header-skeleton";

interface AgentDetailPageProps {
  agentId: string;
}

type Tab =
  | "chat"
  | "conversations"
  | "tool-calls"
  | "logs"
  | "activity"
  | "costs"
  | "about";
const VALID_TABS: Tab[] = [
  "chat",
  "conversations",
  "tool-calls",
  "logs",
  "activity",
  "costs",
  "about",
];

export function AgentDetailPage({ agentId }: AgentDetailPageProps) {
  const { agent, isLoading, error, refetch } = useAgent(agentId);
  const canReadActivity = canAgent(agent, "activity.read");
  const canReadCosts = canAgent(agent, "cost.read");
  const { health } = useAgentHealth(
    agentId,
    canReadActivity &&
      (agent?.status === "RUNNING" || agent?.status === "ERROR"),
  );
  const [tab, setTab] = useQueryState(
    "tab",
    parseAsStringEnum<Tab>(VALID_TABS)
      .withDefault("chat")
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
          ["chat", "Chat"],
          ["conversations", "Conversations"],
          ["tool-calls", "Tool calls"],
          ["logs", "Logs"],
        ] as [Tab, string][])
      : []),
    // Every part of Activity needs activity.read: the runtime diagnostics on
    // their own, the usage sections together with cost.read. The tab itself
    // decides what to show a reader who has only the first.
    ...(canReadActivity ? ([["activity", "Activity"]] as [Tab, string][]) : []),
    // Costs is gated on cost.read alone, independent of activity.read: a custom
    // Agent Access Role can grant one Permission without the other, and this is
    // the only tab that surfaces cost.read on its own — Activity's usage section
    // needs activity.read too.
    ...(canReadCosts ? ([["costs", "Costs"]] as [Tab, string][]) : []),
    ["about", "About"],
  ];
  const resolvedTab = tabs.some(([key]) => key === tab) ? tab : tabs[0][0];

  const isRunning = agent?.status === "RUNNING";
  const isAgentWorking = isRunning && health?.status === "ok";
  const canManageLifecycle = canAgent(agent, "agent.lifecycle.manage");
  const canManageAccess = canAgent(agent, "agent.access.manage");
  const canManageConnections = canAgent(agent, "agent.update");
  const connections = useCommunicationConnections(agent?.id ?? "");
  // The built-in Chat tab lazily provisions a "web" Connection on first send so people
  // can try the Agent without setting anything up; it is not a real messaging platform
  // for this nudge.
  const externalConnections = connections.data?.filter((connection) => connection.platformKey !== "web");
  const needsMessagingSetup =
    !connections.isPending && externalConnections?.length === 0;
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
                {canManageLifecycle && <AgentLifecycleMenu agent={agent} />}
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

            {canManageLifecycle && <AgentUpdateBanner agent={agent} />}

            {/* The classified provisioning failure comes off the Agent itself, so
                it renders on first paint and does not depend on health polling —
                which is also gated on activity.read. Health only explains a
                runtime fault on an Agent that did start. */}
            {agent.status === "ERROR" && agent.lastError ? (
              <AgentErrorBanner failure={agent.lastError} />
            ) : (
              (agent.status === "ERROR" ||
                health?.status === "crashed" ||
                health?.status === "error") &&
              health?.reason && <AgentHealthErrorBanner reason={health.reason} />
            )}

            {needsMessagingSetup && (
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
                          Web chat only
                        </span>
                      </div>
                      <div
                        className="text-[0.95rem] font-semibold"
                        style={{ color: "var(--ink)" }}
                      >
                        Bring {agent.name} to your messaging tools
                      </div>
                      <p
                        className="mb-0 mt-1 text-[0.844rem] leading-relaxed"
                        style={{ color: "var(--ink-3)" }}
                      >
                        {agent.name} is available in Web Chat. Add a connection
                        so your team can also message {agent.name} from Slack,
                        Teams, Telegram, or Discord.
                      </p>
                    </div>
                  </div>
                  {canManageConnections && (
                    <Link
                      href={`${homeHref}/agents/${agent.id}/configuration?section=channels&connect=true`}
                      className="af-btn af-btn-primary af-btn-sm flex-shrink-0 self-start sm:self-auto"
                    >
                      <Plus size={14} /> Add messaging connection
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

            {resolvedTab === "chat" && (
              <ChatTab agent={agent} isAgentWorking={isAgentWorking} />
            )}
            {resolvedTab === "conversations" && (
              <ConversationsTab agent={agent} />
            )}
            {resolvedTab === "tool-calls" && <ToolCallsTab agent={agent} />}
            {resolvedTab === "logs" && <LogsTab agent={agent} />}
            {resolvedTab === "activity" && <ActivityTab agent={agent} />}
            {resolvedTab === "costs" && <AgentCostsPanel agentId={agent.id} />}
            {resolvedTab === "about" && <AboutTab agent={agent} />}
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
