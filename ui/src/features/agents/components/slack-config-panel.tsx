"use client";

import { useState } from "react";
import { SlackIcon, XIcon, PlusIcon } from "@/components/icons";
import type { Agent } from "../schemas";
import { useSlackChannels } from "../hooks/use-slack-channels";
import { useSlackUsers } from "../hooks/use-slack-users";
import { useUpdateAgent } from "../hooks/use-update-agent";

interface SlackConfigPanelProps {
  agent: Agent;
  onSaved?: () => void;
}

export function SlackConfigPanel({ agent, onSaved }: SlackConfigPanelProps) {
  const { channels, isLoading: chLoading } = useSlackChannels(agent.id);
  const { users, isLoading: uLoading } = useSlackUsers(agent.id);
  const updateAgent = useUpdateAgent();

  const isRunning = agent.status === "RUNNING";

  const [channelIds, setChannelIds] = useState<string[]>(agent.slackChannelIds);
  const [userIds, setUserIds] = useState<string[]>(agent.slackDmUserIds);
  const [groupPolicy, setGroupPolicy] = useState<"open" | "allowlist">(agent.slackGroupPolicy);
  const [dmPolicy, setDmPolicy] = useState<"off" | "open" | "allowlist" | "pairing">(agent.slackDmPolicy);
  const [userListCleared, setUserListCleared] = useState(false);
  const [channelSearch, setChannelSearch] = useState("");
  const [userSearch, setUserSearch] = useState("");
  const [channelFocused, setChannelFocused] = useState(false);
  const [userFocused, setUserFocused] = useState(false);

  function handleDmPolicyChange(v: "off" | "open" | "allowlist" | "pairing") {
    setDmPolicy(v);
    if (v === "pairing" && userIds.length > 0) {
      setUserIds([]);
      setUserListCleared(true);
    } else {
      setUserListCleared(false);
    }
  }
  const [saved, setSaved] = useState(false);

  const selectedChannels = channels.filter((c) => channelIds.includes(c.id));
  const availableChannels = channels.filter(
    (c) =>
      !channelIds.includes(c.id) &&
      (channelSearch === "" || c.name.toLowerCase().includes(channelSearch.toLowerCase())),
  );

  const selectedUsers = users.filter((u) => userIds.includes(u.id));
  const availableUsers = users.filter(
    (u) =>
      !userIds.includes(u.id) &&
      (userSearch === "" ||
        u.name.toLowerCase().includes(userSearch.toLowerCase()) ||
        u.realName.toLowerCase().includes(userSearch.toLowerCase())),
  );

  async function handleSave() {
    try {
      await updateAgent.mutateAsync({
        agentId: agent.id,
        slackChannelIds: channelIds,
        slackDmUserIds: userIds,
        slackGroupPolicy: groupPolicy,
        slackDmPolicy: dmPolicy,
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
      onSaved?.();
    } catch {
      // error shown via updateAgent.error
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <section className="flex flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <label
            htmlFor="slack-group-policy"
            className="font-medium text-[0.844rem]"
            style={{ color: "var(--ink)" }}
          >
            Channel access
          </label>
          <select
            id="slack-group-policy"
            className="af-input"
            value={groupPolicy}
            disabled={isRunning}
            onChange={(e) => setGroupPolicy(e.target.value as "open" | "allowlist")}
          >
            <option value="open">Open — respond in any channel</option>
            <option value="allowlist">Allowlist — only allowed channels</option>
          </select>
        </div>

        {groupPolicy === "allowlist" && (
          <div className="flex flex-col gap-2">
            {selectedChannels.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {selectedChannels.map((c) => (
                  <span
                    key={c.id}
                    className="inline-flex items-center gap-1 text-[0.781rem] px-2.5 py-1 rounded-full"
                    style={{ background: "var(--bg-soft)", border: "1px solid var(--line)", color: "var(--ink-2)" }}
                  >
                    <SlackIcon style={{ width: 12, height: 12, flexShrink: 0 }} />
                    #{c.name}
                    <button
                      className="ml-0.5 rounded-full flex items-center"
                      style={{ color: "var(--ink-4)" }}
                      disabled={isRunning}
                      onClick={() => setChannelIds((ids) => ids.filter((id) => id !== c.id))}
                    >
                      <XIcon style={{ width: 12, height: 12 }} />
                    </button>
                  </span>
                ))}
              </div>
            )}

            <div className="relative">
              <input
                className="af-input text-[0.844rem]"
                placeholder={chLoading ? "Loading channels…" : "Search channels to add"}
                value={channelSearch}
                onChange={(e) => setChannelSearch(e.target.value)}
                onFocus={() => setChannelFocused(true)}
                onBlur={() => setTimeout(() => setChannelFocused(false), 150)}
                disabled={chLoading || isRunning}
              />
              {channelFocused && availableChannels.length > 0 && (
                <div
                  className="absolute top-full mt-1 left-0 right-0 rounded-xl z-10 max-h-48 overflow-y-auto"
                  style={{ background: "var(--bg-elev)", border: "1px solid var(--line)", boxShadow: "var(--shadow-pop)" }}
                >
                  {availableChannels.slice(0, 20).map((c) => (
                    <button
                      key={c.id}
                      className="w-full flex items-center gap-2 px-3.5 py-2.5 text-[0.8125rem] text-left hover:bg-[var(--bg-soft)] transition-colors"
                      style={{ color: "var(--ink-2)" }}
                      onClick={() => {
                        setChannelIds((ids) => [...ids, c.id]);
                        setChannelSearch("");
                      }}
                    >
                      <PlusIcon style={{ width: 14, height: 14, flexShrink: 0, color: "var(--ink-4)" }} />
                      #{c.name}
                    </button>
                  ))}
                </div>
              )}
              {channelFocused && !chLoading && availableChannels.length === 0 && (
                <div
                  className="absolute top-full mt-1 left-0 right-0 rounded-xl px-3.5 py-2.5 text-[0.8125rem]"
                  style={{ background: "var(--bg-elev)", border: "1px solid var(--line)", color: "var(--ink-4)" }}
                >
                  No channels found
                </div>
              )}
            </div>
          </div>
        )}
      </section>

      <section className="flex flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <label
            htmlFor="slack-dm-policy"
            className="font-medium text-[0.844rem]"
            style={{ color: "var(--ink)" }}
          >
            Direct messages
          </label>
          <select
            id="slack-dm-policy"
            className="af-input"
            value={dmPolicy}
            disabled={isRunning}
            onChange={(e) => handleDmPolicyChange(e.target.value as "off" | "open" | "allowlist" | "pairing")}
          >
            <option value="off">Off — ignore direct messages</option>
            <option value="open">Open — anyone can DM</option>
            <option value="allowlist">Allowlist — only allowed users</option>
            <option value="pairing">Pairing — users must pair first</option>
          </select>
        </div>

        {(dmPolicy === "allowlist" || dmPolicy === "pairing") && (
          <div className="flex flex-col gap-2">
            {userListCleared && (
              <p className="text-[0.781rem] leading-[1.5]" style={{ color: "var(--ink-4)" }}>
                User list cleared — all users will need to pair to gain access.
              </p>
            )}
            {selectedUsers.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {selectedUsers.map((u) => (
                  <span
                    key={u.id}
                    className="inline-flex items-center gap-1 text-[0.781rem] px-2.5 py-1 rounded-full"
                    style={{ background: "var(--bg-soft)", border: "1px solid var(--line)", color: "var(--ink-2)" }}
                  >
                    {u.realName || u.name}
                    <button
                      className="ml-0.5 rounded-full flex items-center"
                      style={{ color: "var(--ink-4)" }}
                      disabled={isRunning}
                      onClick={() => setUserIds((ids) => ids.filter((id) => id !== u.id))}
                    >
                      <XIcon style={{ width: 12, height: 12 }} />
                    </button>
                  </span>
                ))}
              </div>
            )}

            <div className="relative">
              <input
                className="af-input text-[0.844rem]"
                placeholder={uLoading ? "Loading users…" : "Search users to add"}
                value={userSearch}
                onChange={(e) => setUserSearch(e.target.value)}
                onFocus={() => setUserFocused(true)}
                onBlur={() => setTimeout(() => setUserFocused(false), 150)}
                disabled={uLoading || isRunning}
              />
              {userFocused && availableUsers.length > 0 && (
                <div
                  className="absolute top-full mt-1 left-0 right-0 rounded-xl z-10 max-h-48 overflow-y-auto"
                  style={{ background: "var(--bg-elev)", border: "1px solid var(--line)", boxShadow: "var(--shadow-pop)" }}
                >
                  {availableUsers.slice(0, 20).map((u) => (
                    <button
                      key={u.id}
                      className="w-full flex items-center gap-2 px-3.5 py-2.5 text-[0.8125rem] text-left hover:bg-[var(--bg-soft)] transition-colors"
                      style={{ color: "var(--ink-2)" }}
                      onClick={() => {
                        setUserIds((ids) => [...ids, u.id]);
                        setUserSearch("");
                      }}
                    >
                      <PlusIcon style={{ width: 14, height: 14, flexShrink: 0, color: "var(--ink-4)" }} />
                      {u.realName || u.name}
                    </button>
                  ))}
                </div>
              )}
              {userFocused && !uLoading && availableUsers.length === 0 && (
                <div
                  className="absolute top-full mt-1 left-0 right-0 rounded-xl px-3.5 py-2.5 text-[0.8125rem]"
                  style={{ background: "var(--bg-elev)", border: "1px solid var(--line)", color: "var(--ink-4)" }}
                >
                  No users found
                </div>
              )}
            </div>

            {dmPolicy === "pairing" && (
              <p className="text-[0.781rem] leading-[1.5]" style={{ color: "var(--ink-4)" }}>
                Users not on this list must pair by sending{" "}
                <span className="font-mono">pair &lt;code&gt;</span> to {agent.name} first.
              </p>
            )}
          </div>
        )}
      </section>

      <div className="flex items-center gap-2">
        <button
          className="af-btn af-btn-sm"
          disabled={isRunning || updateAgent.isPending}
          title={isRunning ? "Stop the agent before saving changes" : undefined}
          onClick={() => { void handleSave(); }}
        >
          {updateAgent.isPending ? "Saving…" : saved ? "Saved!" : "Save"}
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
