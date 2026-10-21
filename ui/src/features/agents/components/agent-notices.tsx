"use client";

import Link from "next/link";
import { MessageCircleWarning, Plus } from "lucide-react";

import { useCommunicationConnections } from "@/features/communication-connections/hooks/use-communication-connections";

import type { Agent, AgentHealth } from "../schemas";
import { canAgent } from "../utils";
import { AgentErrorBanner, AgentHealthErrorBanner } from "./agent-error-banner";
import { AgentTelegramSetup } from "./agent-telegram-setup";
import { AgentUpdateBanner, AgentUpdateOutcomeNote } from "./agent-update-banner";
import { PendingModelBanner } from "./pending-model-note";

/**
 * What the Agent page has to tell you before its section: a model change not yet applied,
 * an update on offer and how the last one ended, why it is failing, and the messaging
 * setup it still needs. Every section shows them, Chat and Conversations included, since
 * Chat is where a model change that has not been applied gets noticed.
 */
export function AgentNotices({
  agent,
  health,
  homeHref,
  onOpenChat,
}: {
  agent: Agent;
  health: AgentHealth | null | undefined;
  homeHref: string;
  onOpenChat: () => void;
}) {
  const canManageLifecycle = canAgent(agent, "agent.lifecycle.manage");
  const canManageConnections = canAgent(agent, "agent.update");
  const connections = useCommunicationConnections(agent.id);
  const telegramConnection = connections.data?.find(
    (connection) => connection.platformKey === "agentbarn_telegram" && connection.enabled,
  );
  // The built-in Chat tab lazily provisions a "web" Connection on first send so people can
  // try the Agent without setting anything up; it is not a real messaging platform for
  // this nudge.
  const externalConnections = connections.data?.filter((connection) => connection.platformKey !== "web");
  const needsMessagingSetup = !connections.isPending && externalConnections?.length === 0;

  return (
    <>
      <PendingModelBanner agent={agent} canRestart={canManageLifecycle} />

      {canManageLifecycle && (
        <>
          {/* The path bar offers the update on desktop. */}
          <AgentUpdateBanner agent={agent} className="lg:hidden" />
          <AgentUpdateOutcomeNote
            agent={agent}
            restorePointsHref={`${homeHref}/agents/${agent.id}/configuration?section=restore`}
          />
        </>
      )}

      {/* The classified provisioning failure comes off the Agent itself, so it renders on
          first paint and does not depend on health polling — which is also gated on
          activity.read. Health only explains a runtime fault on an Agent that did start. */}
      {agent.status === "ERROR" && agent.lastError ? (
        <AgentErrorBanner failure={agent.lastError} />
      ) : (
        (agent.status === "ERROR" || health?.status === "crashed" || health?.status === "error") &&
        health?.reason && <AgentHealthErrorBanner reason={health.reason} />
      )}

      {canManageConnections && telegramConnection && (
        <AgentTelegramSetup
          key={telegramConnection.id}
          agent={agent}
          connection={telegramConnection}
          onOpenChat={onOpenChat}
        />
      )}

      {needsMessagingSetup && (
        <MessagingSetupCard agent={agent} homeHref={homeHref} canManageConnections={canManageConnections} />
      )}
    </>
  );
}

function MessagingSetupCard({
  agent,
  homeHref,
  canManageConnections,
}: {
  agent: Agent;
  homeHref: string;
  canManageConnections: boolean;
}) {
  return (
    <div
      className="mb-6 overflow-hidden rounded-2xl"
      style={{
        border: "1px solid color-mix(in srgb, var(--warn) 30%, var(--line))",
        background: "var(--warn-soft)",
      }}
    >
      <div className="flex flex-col gap-4 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 items-start gap-3.5">
          <span
            className="grid h-10 w-10 flex-shrink-0 place-items-center rounded-xl"
            style={{
              background: "color-mix(in srgb, var(--warn) 16%, transparent)",
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
                  border: "1px solid color-mix(in srgb, var(--warn) 28%, transparent)",
                  color: "var(--warn)",
                }}
              >
                Web chat only
              </span>
            </div>
            <div className="text-[0.95rem] font-semibold" style={{ color: "var(--ink)" }}>
              Bring {agent.name} to your messaging tools
            </div>
            <p className="mb-0 mt-1 text-[0.844rem] leading-relaxed" style={{ color: "var(--ink-3)" }}>
              {agent.name} is available in Web Chat. Add a connection so your team can also message{" "}
              {agent.name} from Slack, Teams, Telegram, or Discord.
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
  );
}
