"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useQueryState, parseAsStringEnum, parseAsString } from "nuqs";
import { canAgent, formatModelName } from "../utils";
import { useAgent } from "../hooks/use-agent";
import { useAgentHealth } from "../hooks/use-agent-health";
import { useStartAgent } from "../hooks/use-start-agent";
import { useStopAgent } from "../hooks/use-stop-agent";
import { ChevLeftIcon, PauseIcon, PlayIcon, CogIcon } from "@/components/icons";
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
import {
  canOpenConfigTab,
  ConfigDrawer,
  defaultConfigTab,
  DRAWER_TAB_KEYS,
} from "./config-drawer";

interface AgentDetailPageProps {
  agentId: string;
}

type Tab = "conversations" | "tool-calls" | "logs" | "work" | "about";
const VALID_TABS: Tab[] = ["conversations", "tool-calls", "logs", "work", "about"];

function HeaderSkeleton() {
  return (
    <div className="flex items-center gap-5.5 pb-8 animate-pulse">
      <div className="w-18 h-18 rounded-full flex-shrink-0" style={{ background: "var(--bg-soft)" }} />
      <div className="flex-1 flex flex-col gap-2">
        <div className="h-9 w-48 rounded-lg" style={{ background: "var(--bg-soft)" }} />
        <div className="h-3.5 w-32 rounded-md" style={{ background: "var(--bg-soft)" }} />
        <div className="h-3.5 w-20 rounded-md" style={{ background: "var(--bg-soft)" }} />
      </div>
    </div>
  );
}

export function AgentDetailPage({ agentId }: AgentDetailPageProps) {
  const { agent, isLoading, error, refetch } = useAgent(agentId);
  const canReadActivity = canAgent(agent, "activity.read");
  const { health } = useAgentHealth(
    agentId,
    canReadActivity && (agent?.status === "RUNNING" || agent?.status === "ERROR"),
  );
  const stopAgent = useStopAgent();
  const startAgent = useStartAgent();
  const [tab, setTab] = useQueryState(
    "tab",
    parseAsStringEnum<Tab>(VALID_TABS)
      .withDefault("conversations")
      .withOptions({ scroll: false, history: "replace" }),
  );
  const [configTab, setConfigTab] = useQueryState(
    "configTab",
    parseAsStringEnum(DRAWER_TAB_KEYS).withOptions({ history: "replace" }),
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
  const initialConfigTab = agent ? defaultConfigTab(agent) : null;
  const canConfigure = initialConfigTab !== null;
  const authorizedConfigTab =
    agent && configTab && canOpenConfigTab(agent, configTab) ? configTab : null;

  const params = useParams();
  const orgId = typeof params?.orgId === "string" ? params.orgId : null;
  const homeHref = orgId ? `/dashboard/${orgId}` : "/dashboard";

  return (
    <div style={{ background: "var(--bg)" }}>
      <div className="max-w-[73.75rem] mx-auto px-10 pt-7 pb-24">
        <Link
          href={homeHref}
          className="inline-flex items-center gap-1.5 text-[0.8125rem] mb-6 px-2 py-1 -ml-2 rounded-lg hover:bg-[var(--bg-soft)] transition-colors"
          style={{ color: "var(--ink-3)" }}
        >
          <ChevLeftIcon />
          Your team
        </Link>

        {isLoading && <HeaderSkeleton />}

        {error && (
          <AppErrorState
            error={error}
            title="We couldn't load this agent"
            description="The agent may have been deleted or is unavailable."
            onRetry={() => { void refetch(); }}
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
                {agent.model && (
                  <div className="text-[0.906rem] font-mono" style={{ color: "var(--ink-3)" }}>
                    {formatModelName(agent.model)}
                  </div>
                )}
                {agent.slackConfig?.botDisplayName && (
                  <div className="text-[0.875rem] mt-0.5" style={{ color: "var(--ink-4)" }}>
                    @{agent.slackConfig.botDisplayName}
                  </div>
                )}
                <AgentMetaBadges agent={agent} variant="full" className="mt-2" />
                <div className="mt-2">
                  <StatusLine status={agent.status} health={health} />
                </div>
              </div>
              <div className="flex gap-2">
                {isRunning && canManageLifecycle && (
                  <button
                    className="af-btn"
                    disabled={stopAgent.isPending}
                    onClick={() => { void stopAgent.mutateAsync(agent.id).catch(toastError); }}
                  >
                    <PauseIcon /> {stopAgent.isPending ? "Pausing…" : "Pause"}
                  </button>
                )}
                {!isRunning && canManageLifecycle && (
                  <button
                    className="af-btn"
                    disabled={startAgent.isPending}
                    onClick={() => { void startAgent.mutateAsync(agent.id).catch(toastError); }}
                  >
                    <PlayIcon /> {startAgent.isPending ? "Starting…" : "Start"}
                  </button>
                )}
                {canConfigure && initialConfigTab && (
                  <button className="af-btn" onClick={() => { void setConfigTab(initialConfigTab); }}>
                    <CogIcon /> Configure
                  </button>
                )}
              </div>
            </div>

            {(agent.status === "ERROR" || health?.status === "crashed" || health?.status === "error") && health?.reason && (
              <div
                className="mb-6 rounded-xl px-4 py-3 text-[0.844rem]"
                style={{ background: "color-mix(in srgb, var(--err) 10%, transparent)", border: "1px solid color-mix(in srgb, var(--err) 25%, transparent)", color: "var(--err)" }}
              >
                <span className="font-medium">Error: </span>{health.reason}
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
                  onClick={() => { selectTab(k); }}
                >
                  {l}
                </button>
              ))}
            </div>

            {resolvedTab === "conversations" && <ConversationsTab agent={agent} />}
            {resolvedTab === "tool-calls" && <ToolCallsTab agent={agent} />}
            {resolvedTab === "logs" && <LogsTab agent={agent} />}
            {resolvedTab === "work" && <WorkTab agent={agent} />}
            {resolvedTab === "about" && (
              <AboutTab
                agent={agent}
                onConfigure={
                  canConfigure && initialConfigTab
                    ? () => { void setConfigTab(initialConfigTab); }
                    : undefined
                }
              />
            )}
          </>
        )}
      </div>

      {authorizedConfigTab && agent && (
        <ConfigDrawer
          agent={agent}
          activeTab={authorizedConfigTab}
          onTabChange={(t) => { void setConfigTab(t); }}
          onClose={() => { void setConfigTab(null); }}
        />
      )}

    </div>
  );
}
