"use client";

import { forwardRef, useEffect, useImperativeHandle, useState } from "react";
import type { Agent } from "../schemas";
import { useUpdateAgent } from "../hooks/use-update-agent";
import type { AgentConfigurationEditHandle } from "./agent-configuration-utils";

interface TelegramConfigPanelProps {
  agent: Agent;
  onDirtyChange?: (isDirty: boolean) => void;
  onSaved?: () => void;
}

export const TelegramConfigPanel = forwardRef<
  AgentConfigurationEditHandle,
  TelegramConfigPanelProps
>(function TelegramConfigPanel({ agent, onDirtyChange, onSaved }, ref) {
  const updateAgent = useUpdateAgent();
  const tc = agent.telegramConfig;

  const [groupPolicy, setGroupPolicy] = useState<"open" | "allowlist">(tc?.groupPolicy ?? "open");
  const [dmPolicy, setDmPolicy] = useState<"off" | "open" | "allowlist">(tc?.dmPolicy ?? "open");
  const [allowedChatIds, setAllowedChatIds] = useState((tc?.allowedChatIds ?? []).join(", "));
  const [allowedUserIds, setAllowedUserIds] = useState((tc?.allowedUserIds ?? []).join(", "));
  const parsedChatIds = allowedChatIds.split(",").map((s) => s.trim()).filter(Boolean);
  const isDirty =
    groupPolicy !== (tc?.groupPolicy ?? "open") ||
    dmPolicy !== (tc?.dmPolicy ?? "open") ||
    allowedChatIds !== (tc?.allowedChatIds ?? []).join(", ") ||
    allowedUserIds !== (tc?.allowedUserIds ?? []).join(", ");
  const shouldShowHermesHomeChannelMessage =
    agent.agentType === "hermes" && parsedChatIds.length === 0;

  useEffect(() => {
    onDirtyChange?.(isDirty);
  }, [isDirty, onDirtyChange]);

  async function handleSave() {
    await updateAgent.mutateAsync({
      agentId: agent.id,
      telegramGroupPolicy: groupPolicy,
      telegramDmPolicy: dmPolicy,
      telegramAllowedChatIds: allowedChatIds.split(",").map((s) => s.trim()).filter(Boolean),
      telegramAllowedUserIds: allowedUserIds.split(",").map((s) => s.trim()).filter(Boolean),
    });
    onSaved?.();
  }

  function resetForm() {
    setGroupPolicy(tc?.groupPolicy ?? "open");
    setDmPolicy(tc?.dmPolicy ?? "open");
    setAllowedChatIds((tc?.allowedChatIds ?? []).join(", "));
    setAllowedUserIds((tc?.allowedUserIds ?? []).join(", "));
    updateAgent.reset();
  }

  useImperativeHandle(ref, () => ({ apply: handleSave, cancel: resetForm }));

  return (
    <div className="flex flex-col gap-5">
      <section className="flex flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <label
            htmlFor="tg-group-policy"
            className="font-medium text-[0.844rem]"
            style={{ color: "var(--ink)" }}
          >
            Group chats
          </label>
          <select
            id="tg-group-policy"
            className="af-input"
            value={groupPolicy}
            onChange={(e) => setGroupPolicy(e.target.value as "open" | "allowlist")}
          >
            <option value="open">Open — respond in any group chat</option>
            <option value="allowlist">Allowlist — only allowed group chats</option>
          </select>
        </div>

        {shouldShowHermesHomeChannelMessage && (
          <p className="text-[0.781rem]" style={{ color: "var(--err)" }}>
            Set up a home channel for Hermes if you want scheduled or proactive Telegram delivery.
          </p>
        )}

        {groupPolicy === "allowlist" && (
          <div className="flex flex-col gap-1.5">
            <label className="font-medium text-[0.844rem]" style={{ color: "var(--ink)" }}>
              Allowed chat IDs
            </label>
            <input
              className="af-input font-mono text-[0.8125rem]"
              value={allowedChatIds}
              onChange={(e) => setAllowedChatIds(e.target.value)}
              placeholder="Comma-separated Telegram chat IDs"
            />
            <span className="text-xs" style={{ color: "var(--ink-4)" }}>
              Numeric chat IDs (group chats are typically negative numbers)
            </span>
          </div>
        )}
      </section>

      <section className="flex flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <label
            htmlFor="tg-dm-policy"
            className="font-medium text-[0.844rem]"
            style={{ color: "var(--ink)" }}
          >
            Direct messages
          </label>
          <select
            id="tg-dm-policy"
            className="af-input"
            value={dmPolicy}
            onChange={(e) => setDmPolicy(e.target.value as "off" | "open" | "allowlist")}
          >
            <option value="off">Off — ignore direct messages</option>
            <option value="open">Open — anyone can DM</option>
            <option value="allowlist">Allowlist — only allowed users</option>
          </select>
        </div>

        {dmPolicy === "allowlist" && (
          <div className="flex flex-col gap-1.5">
            <label className="font-medium text-[0.844rem]" style={{ color: "var(--ink)" }}>
              Allowed user IDs
            </label>
            <input
              className="af-input font-mono text-[0.8125rem]"
              value={allowedUserIds}
              onChange={(e) => setAllowedUserIds(e.target.value)}
              placeholder="Comma-separated Telegram user IDs"
            />
            <span className="text-xs" style={{ color: "var(--ink-4)" }}>
              Numeric user IDs — users can find theirs via @userinfobot
            </span>
          </div>
        )}
      </section>

      {updateAgent.error && (
        <span className="text-xs" style={{ color: "var(--err)" }}>
          {updateAgent.error instanceof Error ? updateAgent.error.message : "Save failed"}
        </span>
      )}
      {onSaved && (
        <button
          type="button"
          className="af-btn af-btn-sm self-start"
          disabled={updateAgent.isPending}
          onClick={() => void handleSave()}
        >
          {updateAgent.isPending ? "Saving…" : "Save & Start"}
        </button>
      )}
    </div>
  );
});
