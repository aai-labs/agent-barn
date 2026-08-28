"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { CommunicationConnectionDiagnostics } from "@/features/communication-connections/components/communication-connection-diagnostics";
import { useCommunicationConnections } from "@/features/communication-connections/hooks/use-communication-connections";

import { useAgent } from "../hooks/use-agent";
import { canAgent } from "../utils";

export function AgentCommunicationConnectionDetailPage({
  agentId,
  connectionId,
}: {
  agentId: string;
  connectionId: string;
}) {
  const { agent, isLoading: isLoadingAgent, error: agentError, refetch: refetchAgent } = useAgent(agentId);
  const connections = useCommunicationConnections(agentId);

  if (isLoadingAgent || connections.isPending) {
    return (
      <div className="af-page animate-pulse">
        <div className="h-6 w-56 rounded-lg" style={{ background: "var(--bg-soft)" }} />
        <div className="mt-6 h-96 rounded-2xl" style={{ background: "var(--bg-soft)" }} />
      </div>
    );
  }

  if (agentError || !agent) {
    return (
      <div className="af-page">
        <AppErrorState error={agentError} title="We couldn't load this agent" onRetry={() => void refetchAgent()} />
      </div>
    );
  }

  if (connections.error) {
    return (
      <div className="af-page">
        <AppErrorState error={connections.error} title="We couldn't load this connection" onRetry={() => void connections.refetch()} />
      </div>
    );
  }

  const connection = connections.data?.find((candidate) => candidate.id === connectionId);
  if (!connection) {
    return (
      <div className="af-page">
        <h1 className="m-0 text-2xl font-semibold" style={{ color: "var(--ink)" }}>Connection not found</h1>
        <p style={{ color: "var(--ink-3)" }}>This messaging connection is unavailable or you no longer have access to it.</p>
      </div>
    );
  }

  return (
    <div style={{ background: "var(--bg)" }}>
      <main className="af-page">
        <Link
          href={`/dashboard/${agent.organizationId}/agents/${agent.id}/configuration?section=channels`}
          className="mb-6 inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-[0.8125rem] transition-colors hover:bg-[var(--bg-soft)]"
          style={{ color: "var(--ink-3)" }}
        >
          <ArrowLeft size={14} /> Back to messaging connections
        </Link>
        <h1 className="m-0 text-[2rem] font-semibold tracking-[-0.025em]" style={{ color: "var(--ink)" }}>
          {connection.displayName}
        </h1>
        <p className="mb-0 mt-1 text-[0.9rem]" style={{ color: "var(--ink-3)" }}>
          Communication details and recovery controls for {agent.name}.
        </p>
        <CommunicationConnectionDiagnostics
          agentId={agent.id}
          connection={connection}
          canEdit={canAgent(agent, "agent.update")}
          alwaysExpanded
        />
      </main>
    </div>
  );
}
