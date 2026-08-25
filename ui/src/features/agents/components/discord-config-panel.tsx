"use client";

import { forwardRef, useEffect, useImperativeHandle, useState } from "react";

import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { useUpdateAgent } from "../hooks/use-update-agent";
import type { Agent } from "../schemas";
import type { AgentConfigurationEditHandle } from "./agent-configuration-utils";

interface DiscordConfigPanelProps {
  agent: Agent;
  onDirtyChange?: (isDirty: boolean) => void;
  onValidChange?: (isValid: boolean) => void;
  onSaved?: () => void;
}

function parseIds(value: string): string[] {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

export const DiscordConfigPanel = forwardRef<
  AgentConfigurationEditHandle,
  DiscordConfigPanelProps
>(function DiscordConfigPanel({ agent, onDirtyChange, onValidChange, onSaved }, ref) {
  const updateAgent = useUpdateAgent();
  const config = agent.discordConfig;
  const [groupPolicy, setGroupPolicy] = useState<"open" | "allowlist">(
    config?.groupPolicy ?? "allowlist",
  );
  const [guildIds, setGuildIds] = useState((config?.guildIds ?? []).join(", "));
  const [channelIds, setChannelIds] = useState(
    (config?.allowedChannelIds ?? []).join(", "),
  );
  const [allowAllUsers, setAllowAllUsers] = useState(config?.allowAllUsers ?? true);
  const [userIds, setUserIds] = useState((config?.allowedUserIds ?? []).join(", "));
  const [roleIds, setRoleIds] = useState((config?.allowedRoleIds ?? []).join(", "));
  const [homeChannelId, setHomeChannelId] = useState(config?.homeChannelId ?? "");
  const [requireMention, setRequireMention] = useState(config?.requireMention ?? true);
  const isDirty =
    groupPolicy !== (config?.groupPolicy ?? "allowlist") ||
    guildIds !== (config?.guildIds ?? []).join(", ") ||
    channelIds !== (config?.allowedChannelIds ?? []).join(", ") ||
    allowAllUsers !== (config?.allowAllUsers ?? true) ||
    userIds !== (config?.allowedUserIds ?? []).join(", ") ||
    roleIds !== (config?.allowedRoleIds ?? []).join(", ") ||
    homeChannelId !== (config?.homeChannelId ?? "") ||
    requireMention !== (config?.requireMention ?? true);
  const isAccessValid = allowAllUsers || parseIds(userIds).length > 0 || parseIds(roleIds).length > 0;

  useEffect(() => {
    onDirtyChange?.(isDirty);
  }, [isDirty, onDirtyChange]);

  useEffect(() => {
    onValidChange?.(isAccessValid);
  }, [isAccessValid, onValidChange]);

  async function handleSave() {
    if (!isAccessValid) {
      throw new Error("Add at least one allowed user or role, or turn on Allow all users.");
    }
    await updateAgent.mutateAsync({
      agentId: agent.id,
      discordGroupPolicy: groupPolicy,
      discordGuildIds: parseIds(guildIds),
      discordAllowedChannelIds: parseIds(channelIds),
      discordAllowAllUsers: allowAllUsers,
      discordAllowedUserIds: parseIds(userIds),
      discordAllowedRoleIds: parseIds(roleIds),
      discordHomeChannelId: homeChannelId.trim() || null,
      discordRequireMention: requireMention,
    });
    onSaved?.();
  }

  function resetForm() {
    setGroupPolicy(config?.groupPolicy ?? "allowlist");
    setGuildIds((config?.guildIds ?? []).join(", "));
    setChannelIds((config?.allowedChannelIds ?? []).join(", "));
    setAllowAllUsers(config?.allowAllUsers ?? true);
    setUserIds((config?.allowedUserIds ?? []).join(", "));
    setRoleIds((config?.allowedRoleIds ?? []).join(", "));
    setHomeChannelId(config?.homeChannelId ?? "");
    setRequireMention(config?.requireMention ?? true);
    updateAgent.reset();
  }

  useImperativeHandle(ref, () => ({ apply: handleSave, cancel: resetForm }));

  return (
    <div className="flex flex-col gap-5">
      <p className="m-0 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
        Configure which Discord servers, channels, and operators {agent.name} can interact with.
        Direct messages remain disabled.
      </p>

      <div className="flex flex-col gap-1.5">
        <label htmlFor="discord-group-policy" className="font-medium text-[0.844rem]" style={{ color: "var(--ink)" }}>
          Server access
        </label>
        <Select
          value={groupPolicy}
          onValueChange={(value) => setGroupPolicy(value as "open" | "allowlist")}
        >
          <SelectTrigger id="discord-group-policy" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectItem value="allowlist">Allowlist — only configured servers</SelectItem>
              <SelectItem value="open">Open — any server containing this bot</SelectItem>
            </SelectGroup>
          </SelectContent>
        </Select>
      </div>

      {groupPolicy === "allowlist" && (
        <label className="flex flex-col gap-1.5 font-medium text-[0.844rem]" style={{ color: "var(--ink)" }}>
          Allowed server IDs
          <input className="af-input font-mono text-[0.8125rem]" value={guildIds} onChange={(event) => setGuildIds(event.target.value)} placeholder="Comma-separated Discord server IDs" />
        </label>
      )}

      <label className="flex flex-col gap-1.5 font-medium text-[0.844rem]" style={{ color: "var(--ink)" }}>
        Allowed channel IDs
        <input className="af-input font-mono text-[0.8125rem]" value={channelIds} onChange={(event) => setChannelIds(event.target.value)} placeholder="Comma-separated channel IDs" />
      </label>

      <label className="flex items-start gap-2 text-[0.844rem]" style={{ color: "var(--ink-2)" }}>
        <input type="checkbox" className="mt-0.5" checked={allowAllUsers} onChange={(event) => setAllowAllUsers(event.target.checked)} />
        <span><span className="font-medium" style={{ color: "var(--ink)" }}>Allow all users</span><br /><span className="text-[0.75rem]" style={{ color: "var(--ink-4)" }}>Anyone in an allowed server and channel may interact with this Agent.</span></span>
      </label>

      {!allowAllUsers && (
        <>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <label className="flex flex-col gap-1.5 font-medium text-[0.844rem]" style={{ color: "var(--ink)" }}>
              Allowed user IDs
              <input className="af-input font-mono text-[0.8125rem]" value={userIds} onChange={(event) => setUserIds(event.target.value)} placeholder="Comma-separated user IDs" />
            </label>
            <label className="flex flex-col gap-1.5 font-medium text-[0.844rem]" style={{ color: "var(--ink)" }}>
              Allowed role IDs
              <input className="af-input font-mono text-[0.8125rem]" value={roleIds} onChange={(event) => setRoleIds(event.target.value)} placeholder="Comma-separated role IDs" />
            </label>
          </div>
          {!isAccessValid && (
            <div className="rounded-lg px-3 py-2 text-[0.78rem]" style={{ color: "var(--err)", background: "color-mix(in srgb, var(--err) 8%, transparent)" }}>
              Add at least one allowed user or role, or turn on Allow all users.
            </div>
          )}
        </>
      )}

      <label className="flex flex-col gap-1.5 font-medium text-[0.844rem]" style={{ color: "var(--ink)" }}>
        Alert destination channel ID
        <input className="af-input font-mono text-[0.8125rem]" value={homeChannelId} onChange={(event) => setHomeChannelId(event.target.value)} placeholder="Optional channel ID" />
      </label>

      <label className="flex items-center gap-2 text-[0.844rem]" style={{ color: "var(--ink-2)" }}>
        <input type="checkbox" checked={requireMention} onChange={(event) => setRequireMention(event.target.checked)} />
        Require an explicit mention in server channels
      </label>

      {updateAgent.error && (
        <span className="text-xs" style={{ color: "var(--err)" }}>
          {updateAgent.error instanceof Error ? updateAgent.error.message : "Save failed"}
        </span>
      )}
    </div>
  );
});
