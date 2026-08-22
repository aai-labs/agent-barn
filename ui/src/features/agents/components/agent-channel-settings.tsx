"use client";

import { useRef, useState } from "react";

import { useAgentApplyAndRestart } from "../hooks/use-agent-apply-and-restart";
import type { Agent } from "../schemas";
import { AgentConfigurationSection } from "./agent-configuration-section";
import type { AgentConfigurationEditHandle } from "./agent-configuration-utils";
import { DiscordConfigPanel } from "./discord-config-panel";
import { SlackConfigPanel } from "./slack-config-panel";
import { TelegramConfigPanel } from "./telegram-config-panel";

export function AgentChannelSettings({
  agent,
  canEdit,
  editing,
  onEdit,
}: {
  agent: Agent;
  canEdit: boolean;
  editing: boolean;
  onEdit: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const [isDirty, setIsDirty] = useState(false);
  const [isValid, setIsValid] = useState(true);
  const panelRef = useRef<AgentConfigurationEditHandle>(null);
  const { applyAndRestart } = useAgentApplyAndRestart(agent);
  const editable = canEdit && agent.platform !== "teams";
  const telegram = agent.telegramConfig;
  const slack = agent.slackConfig;
  const discord = agent.discordConfig;

  async function applyChanges() {
    const action = panelRef.current;
    if (!action) return;
    await applyAndRestart(action.apply);
  }

  function cancelChanges() {
    panelRef.current?.cancel();
    setIsDirty(false);
    onEdit();
  }

  async function copyEndpoint() {
    if (!agent.webhookUrl) return;
    await navigator.clipboard.writeText(agent.webhookUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 1600);
  }

  return (
    <AgentConfigurationSection
      title={agent.platform === "teams" ? "Endpoint" : "Channels & endpoint"}
      description="Messaging routes are separate from the Agent's template and can be changed without creating a new override."
      canEdit={editable}
      editing={editing}
      onEdit={onEdit}
      onApply={applyChanges}
      onCancel={cancelChanges}
      onApplied={onEdit}
      applyDisabled={!isDirty || !isValid}
      restartOnApply={agent.status === "RUNNING"}
    >
      {editing && editable ? (
        agent.platform === "slack" ? (
          <SlackConfigPanel
            ref={panelRef}
            agent={agent}
            isRunning={false}
            onDirtyChange={setIsDirty}
          />
        ) : agent.platform === "telegram" ? (
          <TelegramConfigPanel
            ref={panelRef}
            agent={agent}
            onDirtyChange={setIsDirty}
          />
        ) : (
          <DiscordConfigPanel
            ref={panelRef}
            agent={agent}
            onDirtyChange={setIsDirty}
            onValidChange={setIsValid}
          />
        )
      ) : (
        <div className="flex flex-col gap-5">
          {agent.platform === "slack" && slack && (
            <dl className="grid gap-x-8 gap-y-4 sm:grid-cols-2">
              <div>
                <dt className="text-[0.72rem] font-semibold uppercase tracking-[0.08em]" style={{ color: "var(--ink-4)" }}>Channel access</dt>
                <dd className="mb-0 mt-1 text-[0.9rem]" style={{ color: "var(--ink-2)" }}>{slack.groupPolicy === "open" ? "Open" : "Allowlist"}</dd>
              </div>
              <div>
                <dt className="text-[0.72rem] font-semibold uppercase tracking-[0.08em]" style={{ color: "var(--ink-4)" }}>Direct messages</dt>
                <dd className="mb-0 mt-1 text-[0.9rem]" style={{ color: "var(--ink-2)" }}>{slack.dmPolicy === "open" ? "Open" : slack.dmPolicy === "allowlist" ? "Allowlist" : "Off"}</dd>
              </div>
              <div>
                <dt className="text-[0.72rem] font-semibold uppercase tracking-[0.08em]" style={{ color: "var(--ink-4)" }}>Allowed channels</dt>
                <dd className="mb-0 mt-1 text-[0.9rem]" style={{ color: "var(--ink-2)" }}>{slack.channelIds.length || "None"}</dd>
              </div>
              <div>
                <dt className="text-[0.72rem] font-semibold uppercase tracking-[0.08em]" style={{ color: "var(--ink-4)" }}>Allowed users</dt>
                <dd className="mb-0 mt-1 text-[0.9rem]" style={{ color: "var(--ink-2)" }}>{slack.dmUserIds.length || "None"}</dd>
              </div>
            </dl>
          )}

          {agent.platform === "telegram" && telegram && (
            <dl className="grid gap-x-8 gap-y-4 sm:grid-cols-2">
              <div>
                <dt className="text-[0.72rem] font-semibold uppercase tracking-[0.08em]" style={{ color: "var(--ink-4)" }}>Bot</dt>
                <dd className="mb-0 mt-1 font-mono text-[0.84rem]" style={{ color: "var(--ink-2)" }}>{telegram.botUsername ? `@${telegram.botUsername}` : "Configured"}</dd>
              </div>
              <div>
                <dt className="text-[0.72rem] font-semibold uppercase tracking-[0.08em]" style={{ color: "var(--ink-4)" }}>Group chats</dt>
                <dd className="mb-0 mt-1 text-[0.9rem]" style={{ color: "var(--ink-2)" }}>{telegram.groupPolicy === "open" ? "Open" : "Allowlist"}</dd>
              </div>
              <div>
                <dt className="text-[0.72rem] font-semibold uppercase tracking-[0.08em]" style={{ color: "var(--ink-4)" }}>Direct messages</dt>
                <dd className="mb-0 mt-1 text-[0.9rem]" style={{ color: "var(--ink-2)" }}>{telegram.dmPolicy === "open" ? "Open" : telegram.dmPolicy === "allowlist" ? "Allowlist" : "Off"}</dd>
              </div>
              <div>
                <dt className="text-[0.72rem] font-semibold uppercase tracking-[0.08em]" style={{ color: "var(--ink-4)" }}>Allowed chats / users</dt>
                <dd className="mb-0 mt-1 text-[0.9rem]" style={{ color: "var(--ink-2)" }}>{telegram.allowedChatIds.length} chats · {telegram.allowedUserIds.length} users</dd>
              </div>
            </dl>
          )}

          {agent.platform === "discord" && discord && (
            <dl className="grid gap-x-8 gap-y-4 sm:grid-cols-2">
              <div>
                <dt className="text-[0.72rem] font-semibold uppercase tracking-[0.08em]" style={{ color: "var(--ink-4)" }}>Server access</dt>
                <dd className="mb-0 mt-1 text-[0.9rem]" style={{ color: "var(--ink-2)" }}>{discord.groupPolicy === "open" ? "Open" : "Allowlist"}</dd>
              </div>
              <div>
                <dt className="text-[0.72rem] font-semibold uppercase tracking-[0.08em]" style={{ color: "var(--ink-4)" }}>Allowed servers</dt>
                <dd className="mb-0 mt-1 text-[0.9rem]" style={{ color: "var(--ink-2)" }}>{discord.guildIds.length || "None"}</dd>
              </div>
              <div>
                <dt className="text-[0.72rem] font-semibold uppercase tracking-[0.08em]" style={{ color: "var(--ink-4)" }}>Allowed channels</dt>
                <dd className="mb-0 mt-1 text-[0.9rem]" style={{ color: "var(--ink-2)" }}>{discord.allowedChannelIds.length || "None"}</dd>
              </div>
              <div>
                <dt className="text-[0.72rem] font-semibold uppercase tracking-[0.08em]" style={{ color: "var(--ink-4)" }}>Allowed operators</dt>
                <dd className="mb-0 mt-1 text-[0.9rem]" style={{ color: "var(--ink-2)" }}>{discord.allowAllUsers ? "All users" : `${discord.allowedUserIds.length} users · ${discord.allowedRoleIds.length} roles`}</dd>
              </div>
              <div>
                <dt className="text-[0.72rem] font-semibold uppercase tracking-[0.08em]" style={{ color: "var(--ink-4)" }}>Mention gating</dt>
                <dd className="mb-0 mt-1 text-[0.9rem]" style={{ color: "var(--ink-2)" }}>{discord.requireMention ? "Required" : "Not required"}</dd>
              </div>
              <div>
                <dt className="text-[0.72rem] font-semibold uppercase tracking-[0.08em]" style={{ color: "var(--ink-4)" }}>Alert destination</dt>
                <dd className="mb-0 mt-1 break-all font-mono text-[0.84rem]" style={{ color: "var(--ink-2)" }}>{discord.homeChannelId || "None"}</dd>
              </div>
            </dl>
          )}

          {agent.platform === "teams" && (
            <div className="flex flex-col gap-3">
              <p className="m-0 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
                Microsoft Teams delivers messages through this webhook. Configure it in your Azure Bot registration.
              </p>
              {agent.webhookUrl ? (
                <div className="flex items-center gap-2 rounded-xl p-3 font-mono text-[0.8rem]" style={{ background: "var(--bg-soft)", border: "1px solid var(--line)" }}>
                  <span className="min-w-0 flex-1 break-all" style={{ color: "var(--ink-2)" }}>{agent.webhookUrl}</span>
                  <button type="button" className="af-btn af-btn-sm shrink-0" onClick={() => void copyEndpoint()}>{copied ? "Copied!" : "Copy"}</button>
                </div>
              ) : (
                <p className="m-0 text-[0.84rem]" style={{ color: "var(--ink-4)" }}>The endpoint becomes available after the API external URL is configured.</p>
              )}
            </div>
          )}

          {agent.platform !== "teams" && !slack && !telegram && !discord && (
            <p className="m-0 text-[0.84rem]" style={{ color: "var(--ink-4)" }}>No channel configuration has been recorded.</p>
          )}
        </div>
      )}
    </AgentConfigurationSection>
  );
}
