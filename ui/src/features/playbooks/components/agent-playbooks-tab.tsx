"use client";

import type { Agent } from "@/features/agents/schemas";

import { useAgentPlaybookRuns } from "../hooks/use-agent-playbook-runs";
import { PlaybookExtractionForm } from "./playbook-extraction-form";
import { PlaybookRunList } from "./playbook-run-list";

/** Shown only to Organization Owners and Admins who can read the Agent's activity. */
export function AgentPlaybooksTab({ agent }: { agent: Agent }) {
  const runs = useAgentPlaybookRuns(agent.id, true);
  return (
    <div>
      <PlaybookExtractionForm key={agent.id} agent={agent} hasActiveRun={runs.hasActiveRun} />
      <PlaybookRunList
        agentId={agent.id}
        runs={runs.runs}
        isLoading={runs.isLoading}
        error={runs.error}
        refetch={runs.refetch}
        hasMore={runs.hasMore}
        loadMore={runs.loadMore}
        isLoadingMore={runs.isLoadingMore}
      />
    </div>
  );
}
