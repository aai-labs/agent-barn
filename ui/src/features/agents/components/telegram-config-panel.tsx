"use client";

import { useState } from "react";
import type { Agent } from "../schemas";
import { useUpdateAgent } from "../hooks/use-update-agent";

interface TelegramConfigPanelProps {
  agent: Agent;
  onSaved?: () => void;
}

export function TelegramConfigPanel({ agent, onSaved }: TelegramConfigPanelProps) {
  const updateAgent = useUpdateAgent();
  const tc = agent.telegramConfig;

  const [groupPolicy, setGroupPolicy] = useState<"open" | "allowlist">(tc?.groupPolicy ?? "open");
  const [dmPolicy, setDmPolicy] = useState<"off" | "open" | "allowlist">(tc?.dmPolicy ?? "open");
  const [allowedChatIds, setAllowedChatIds] = useState((tc?.allowedChatIds ?? []).join(", "));
  const [allowedUserIds, setAllowedUserIds] = useState((tc?.allowedUserIds ?? []).join(", "));
  const [saved, setSaved] = useState(false);
  const parsedChatIds = allowedChatIds.split(",").map((s) => s.trim()).filter(Boolean);
  const shouldShowHermesHomeChannelMessage =
    agent.agentType === "hermes" && parsedChatIds.length === 0;

  async function handleSave() {
    try {
      await updateAgent.mutateAsync({
        agentId: agent.id,
        telegramGroupPolicy: groupPolicy,
        telegramDmPolicy: dmPolicy,
        telegramAllowedChatIds: allowedChatIds.split(",").map((s) => s.trim()).filter(Boolean),
        telegramAllowedUserIds: allowedUserIds.split(",").map((s) => s.trim()).filter(Boolean),
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
      onSaved?.();
    } catch {
      // error displayed via updateAgent.error
    }
  }

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

      <div className="flex items-center gap-2">
        <button
          className="af-btn af-btn-sm"
          disabled={updateAgent.isPending}
          onClick={() => { void handleSave(); }}
        >
          {updateAgent.isPending ? "Saving…" : saved ? "Saved!" : "Save & Start"}
        </button>
        {updateAgent.error && (
          <span className="text-xs" style={{ color: "var(--err)" }}>
            {updateAgent.error instanceof Error ? updateAgent.error.message : "Save failed"}
          </span>
        )}
      </div>
    </div>
  );
}
