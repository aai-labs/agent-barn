"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useQueryState, parseAsStringEnum, parseAsString } from "nuqs";
import { canAgent, currentModelOf, formatModelName } from "../utils";
import { ModelSourceBadge } from "./model-source-badge";
import { useAgent } from "../hooks/use-agent";
import { useAgentHealth } from "../hooks/use-agent-health";
import { ShareIcon } from "@/components/icons";
import { AppErrorState } from "@/components/app-error-state";
import { AgentCostsPanel } from "@/features/costs/components/agent-costs-panel";
import { AgentResourceUsageTab } from "@/features/resource-usage/components/agent-resource-usage-tab";
import { AgentAvatar } from "./agent-avatar";
import { AgentLifecycleMenu } from "./agent-lifecycle-menu";
import { AgentMetaBadges } from "./agent-meta-badges";
import { AgentNotices } from "./agent-notices";
import { StatusLine } from "./status-line";
import { ChatTab } from "./chat-tab";
import { ConversationsTab } from "./conversations-tab";
import { ToolCallsTab } from "./tool-calls-tab";
import { LogsTab } from "./logs-tab";
import { ActivityTab } from "./activity-tab";
import { AgentMemoryTab } from "@/features/agent-memory/components/agent-memory-tab";
import { AgentFiles } from "@/features/artifacts/components/agent-files";
import { WorkflowsPage } from "@/features/workflows/components/workflows-page";
import { useWorkflowCapabilities } from "@/features/workflows/hooks/use-workflows";
import { useActiveOrgRole } from "@/features/organizations/hooks/use-active-org-role";
import { AgentPlaybooksTab } from "@/features/playbooks/components/agent-playbooks-tab";
import { AboutTab } from "./about-tab";
import { ShareDialog } from "./share-dialog";
import { AgentDetailHeaderSkeleton } from "./agent-detail-header-skeleton";
import { useIsDesktop } from "@/features/navigation/hooks/use-is-desktop";
import { cn } from "@/lib/utils";
import {
  AGENT_PAGE_TABS,
  AGENT_PAGE_TAB_LABELS,
  DEFAULT_AGENT_TAB,
  visibleAgentPageTabs,
  type AgentPageTab,
} from "../agent-page-tabs";

interface AgentDetailPageProps {
  agentId: string;
}

export function AgentDetailPage({ agentId }: AgentDetailPageProps) {
  const { agent, isLoading, error, refetch } = useAgent(agentId);
  const canReadActivity = canAgent(agent, "activity.read");
  const { role } = useActiveOrgRole();
  const workflowCapabilities = useWorkflowCapabilities(agentId, canAgent(agent, "agent.read"));
  const tabs = visibleAgentPageTabs(agent, role, {
    workflowAuthoring: workflowCapabilities.data?.authoring === true,
  });
  const canExtractPlaybooks = tabs.includes("playbooks");
  // The desktop path bar carries the Agent's lifecycle and Share actions; the page's own
  // copies wait for this check so the two never coexist.
  const isDesktop = useIsDesktop();
  const { health } = useAgentHealth(
    agentId,
    canReadActivity &&
      (agent?.status === "RUNNING" || agent?.status === "ERROR"),
  );
  const [tab, setTab] = useQueryState(
    "tab",
    parseAsStringEnum<AgentPageTab>(AGENT_PAGE_TABS)
      .withDefault(DEFAULT_AGENT_TAB)
      .withOptions({ scroll: false, history: "replace" }),
  );
  const [, setChannel] = useQueryState(
    "channel",
    parseAsString.withOptions({ history: "replace" }),
  );
  const [, setUsageRange] = useQueryState(
    "range",
    parseAsString.withOptions({ history: "replace" }),
  );
  const [workflow, setWorkflow] = useQueryState("workflow", parseAsString.withOptions({ history: "replace" }));

  const [workflowRun, setWorkflowRun] = useQueryState("workflowRun", parseAsString.withOptions({ history: "replace" }));
  const [, setWorkflowView] = useQueryState("workflowView", parseAsString.withOptions({ history: "replace", scroll: false }));
  const [, setWorkflowRunPage] = useQueryState("workflowRunPage", parseAsString.withOptions({ history: "replace", scroll: false }));
  const [startingRun, setStartingRun] = useState(false);

  function selectTab(next: AgentPageTab) {
    void setTab(next);
    // channel is only meaningful on the conversations tab; drop it elsewhere
    if (next !== "conversations") void setChannel(null);
    // likewise the time range, which only the resource usage tab reads
    if (next !== "resource-usage") void setUsageRange(null);
    // and the open workflow, which only the workflows tab reads
    if (next !== "workflows") {
      void setWorkflow(null);
      void setWorkflowRun(null);
      void setWorkflowView(null);
      void setWorkflowRunPage(null);
    }
  }

  // Overview is always visible, and a section the viewer cannot open falls back to it.
  const resolvedTab = tabs.includes(tab) ? tab : DEFAULT_AGENT_TAB;

  const workflowFocus = resolvedTab === "workflows" && (Boolean(workflow) || Boolean(workflowRun) || startingRun);

  const isRunning = agent?.status === "RUNNING";
  const isAgentWorking = isRunning && health?.status === "ok";
  const canManageLifecycle = canAgent(agent, "agent.lifecycle.manage");
  const canManageAccess = canAgent(agent, "agent.access.manage");
  const [shareOpen, setShareOpen] = useState(false);

  const params = useParams();
  const orgId = typeof params?.orgId === "string" ? params.orgId : null;
  const homeHref = orgId ? `/dashboard/${orgId}` : "/dashboard";

  // The shell frames the page (`usePageFrame`): on desktop, Chat and Conversations edge to
  // edge below the path bar, the live Logs at the usual width grown to the window's height.
  // The page only passes that height down to the section, and on Chat and Conversations
  // insets its notices, since the frame there has no margins of its own. All of it is CSS,
  // so what is open stays mounted when the window crosses the breakpoint.
  const fillsPage = resolvedTab === "chat" || resolvedTab === "conversations";
  const fillsHeight = fillsPage || resolvedTab === "logs";
  const passesHeight = cn(fillsHeight && "lg:flex lg:min-h-0 lg:flex-1 lg:flex-col");

  return (
    <div className={passesHeight}>
      <div className={passesHeight}>
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
            {/* The desktop path bar names the Agent and shows its status, runtime, model
                and actions, so the header is for phones. Identity and actions wrap onto
                separate rows when they do not fit side by side, so the buttons sit under
                the name, not over it. */}
            <div hidden={workflowFocus}>
            <div className="flex flex-wrap items-start gap-x-5.5 gap-y-4 pb-8 lg:hidden">
              <div className="flex min-w-0 flex-1 basis-[20rem] items-start gap-4 sm:gap-5.5">
                <AgentAvatar agent={agent} size="xl" />
                <div className="flex-1 min-w-0">
                  <h1
                    className="text-[1.75rem] sm:text-[2.5rem] font-semibold tracking-[-0.028em] m-0 mb-1 leading-[1.1] break-words"
                    style={{ color: "var(--ink)" }}
                  >
                    {agent.name}
                  </h1>
                  {currentModelOf(agent) && (
                    <div className="flex items-center gap-2 text-[0.906rem]" style={{ color: "var(--ink-3)" }}>
                      <span className="font-mono">{formatModelName(currentModelOf(agent))}</span>
                      <ModelSourceBadge source={agent.modelSource} />
                    </div>
                  )}
                  <AgentMetaBadges agent={agent} variant="full" className="mt-2" />
                  <div className="mt-2">
                    <StatusLine status={agent.status} health={health} />
                  </div>
                </div>
              </div>
              {/* Only the actions wait for the width check: the path bar has its own,
                  and two copies of the lifecycle and Share dialogs must not coexist. */}
              {!isDesktop && (
                <div className="flex flex-wrap gap-2">
                  {canManageLifecycle && <AgentLifecycleMenu agent={agent} />}
                  {canManageAccess && (
                    <button className="af-btn" onClick={() => setShareOpen(true)}>
                      <ShareIcon /> Share
                    </button>
                  )}
                </div>
              )}
            </div>

            </div>

            <div className={cn(fillsPage && "lg:px-6 lg:pt-4 lg:empty:hidden")}>
              <AgentNotices
                agent={agent}
                health={health}
                homeHref={homeHref}
                onOpenChat={() => selectTab("chat")}
              />
            </div>

            {/* The path bar names the section on desktop. */}
            <h2
              hidden={workflowFocus}
              className="m-0 mb-7 pb-3 text-[1.125rem] font-semibold lg:hidden"
              style={{ color: "var(--ink)", borderBottom: "1px solid var(--line)" }}
            >
              {AGENT_PAGE_TAB_LABELS[resolvedTab]}
            </h2>

            <div className={cn(fillsHeight && "lg:min-h-0 lg:flex-1")}>
            {resolvedTab === "chat" && (
              <ChatTab agent={agent} isAgentWorking={isAgentWorking} />
            )}
            {resolvedTab === "conversations" && (
              <ConversationsTab agent={agent} />
            )}
            {resolvedTab === "tool-calls" && <ToolCallsTab agent={agent} />}
            {resolvedTab === "logs" && <LogsTab agent={agent} />}
            {resolvedTab === "memory" && canReadActivity && <AgentMemoryTab agent={agent} />}
            {resolvedTab === "files" && <AgentFiles key={`${orgId}:${agent.id}`} agentId={agent.id} />}
            {resolvedTab === "workflows" && orgId && (
              <WorkflowsPage key={`${orgId}:${agent.id}`} agentId={agent.id} organizationId={orgId} embedded onStartingChange={setStartingRun} />
            )}
            {resolvedTab === "playbooks" && canExtractPlaybooks && <AgentPlaybooksTab agent={agent} />}
            {resolvedTab === "activity" && <ActivityTab agent={agent} />}
            {resolvedTab === "costs" && <AgentCostsPanel agentId={agent.id} />}
            {resolvedTab === "resource-usage" && (
              <AgentResourceUsageTab
                agent={agent}
                onOpenActivity={() => {
                  selectTab("activity");
                }}
              />
            )}
            {resolvedTab === "about" && <AboutTab agent={agent} />}
            </div>
          </>
        )}
      </div>

      {agent && canManageAccess && !isDesktop && (
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
