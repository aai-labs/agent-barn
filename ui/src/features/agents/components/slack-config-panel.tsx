"use client";

import { useState } from "react";
import { SlackIcon, XIcon, PlusIcon, LockIcon } from "@/components/icons";
import type { Agent } from "../schemas";
import { useSlackChannels } from "../hooks/use-slack-channels";
import { useSlackUsers } from "../hooks/use-slack-users";
import { useUpdateAgent } from "../hooks/use-update-agent";

interface SlackConfigPanelProps {
  agent: Agent;
  onSaved?: () => void;
}

// Cap rendered dropdown rows for performance; a footer prompts narrowing by search.
const MAX_DROPDOWN_RESULTS = 50;

function userLabel(u: { displayName: string; realName: string; name: string }) {
  return u.displayName || u.realName || u.name;
}

export function SlackConfigPanel({ agent, onSaved }: SlackConfigPanelProps) {
  const { channels, isLoading: chLoading } = useSlackChannels(agent.id);
  const { users, isLoading: uLoading } = useSlackUsers(agent.id);
  const updateAgent = useUpdateAgent();

  const isRunning = agent.status === "RUNNING";

  const [channelIds, setChannelIds] = useState<string[]>(agent.slackConfig?.channelIds ?? []);
  const [userIds, setUserIds] = useState<string[]>(agent.slackConfig?.dmUserIds ?? []);
  const [groupPolicy, setGroupPolicy] = useState<"open" | "allowlist">(agent.slackConfig?.groupPolicy ?? "open");
  const [dmPolicy, setDmPolicy] = useState<"off" | "open" | "allowlist">(agent.slackConfig?.dmPolicy ?? "off");
  const [channelSearch, setChannelSearch] = useState("");
  const [userSearch, setUserSearch] = useState("");
  const [channelFocused, setChannelFocused] = useState(false);
  const [userFocused, setUserFocused] = useState(false);
  const [saved, setSaved] = useState(false);

  const selectedChannels = channelIds
    .map((id) => channels.find((c) => c.id === id))
    .filter((c): c is NonNullable<typeof c> => c !== undefined);
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
        u.realName.toLowerCase().includes(userSearch.toLowerCase()) ||
        u.displayName.toLowerCase().includes(userSearch.toLowerCase())),
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
                {selectedChannels.map((c, i) => (
                  <span
                    key={c.id}
                    className="inline-flex items-center gap-1 text-[0.781rem] px-2.5 py-1 rounded-full"
                    style={{ background: "var(--bg-soft)", border: "1px solid var(--line)", color: "var(--ink-2)" }}
                  >
                    {c.isPrivate
                      ? <LockIcon style={{ width: 12, height: 12, flexShrink: 0, color: "var(--ink-4)" }} />
                      : <SlackIcon style={{ width: 12, height: 12, flexShrink: 0 }} />
                    }
                    #{c.name}
                    {agent.agentType === "hermes" && i === 0 && (
                      <span
                        className="ml-1 text-[0.688rem] px-1.5 py-px rounded-full font-medium"
                        style={{ background: "var(--bg-elev)", border: "1px solid var(--line)", color: "var(--ink-4)" }}
                      >
                        home
                      </span>
                    )}
                    {agent.agentType === "hermes" && i > 0 && !isRunning && (
                      <button
                        className="ml-1 text-[0.688rem] px-1.5 py-px rounded-full transition-colors hover:bg-[var(--bg-elev)]"
                        style={{ color: "var(--ink-3)", border: "1px solid var(--line)" }}
                        onClick={() => setChannelIds((ids) => [c.id, ...ids.filter((id) => id !== c.id)])}
                      >
                        set home
                      </button>
                    )}
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
                  {availableChannels.slice(0, MAX_DROPDOWN_RESULTS).map((c) => (
                    <button
                      key={c.id}
                      className="w-full flex items-center gap-2 px-3.5 py-2.5 text-[0.8125rem] text-left hover:bg-[var(--bg-soft)] transition-colors"
                      style={{ color: "var(--ink-2)" }}
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => {
                        setChannelIds((ids) => [...ids, c.id]);
                        setChannelSearch("");
                      }}
                    >
                      <PlusIcon style={{ width: 14, height: 14, flexShrink: 0, color: "var(--ink-4)" }} />
                      #{c.name}
                      {c.isPrivate && (
                        <LockIcon style={{ width: 11, height: 11, flexShrink: 0, color: "var(--ink-4)" }} />
                      )}
                    </button>
                  ))}
                  {availableChannels.length > MAX_DROPDOWN_RESULTS && (
                    <div className="px-3.5 py-2 text-[0.75rem]" style={{ color: "var(--ink-4)" }}>
                      Keep typing to narrow — {availableChannels.length - MAX_DROPDOWN_RESULTS} more
                    </div>
                  )}
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
            <p className="text-[0.781rem]" style={{ color: "var(--ink-4)" }}>
              Private channels only appear here if the bot is already a member. To add one, use{" "}
              <code className="font-mono">/invite @bot-name</code> in Slack first.
            </p>
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
            onChange={(e) => setDmPolicy(e.target.value as "off" | "open" | "allowlist")}
          >
            <option value="off">Off — ignore direct messages</option>
            <option value="open">Open — anyone can DM</option>
            <option value="allowlist">Allowlist — only allowed users</option>
          </select>
        </div>

        {dmPolicy === "allowlist" && (
          <div className="flex flex-col gap-2">
            {selectedUsers.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {selectedUsers.map((u) => (
                  <span
                    key={u.id}
                    className="inline-flex items-center gap-1 text-[0.781rem] px-2.5 py-1 rounded-full"
                    style={{ background: "var(--bg-soft)", border: "1px solid var(--line)", color: "var(--ink-2)" }}
                  >
                    {userLabel(u)}
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
                  {availableUsers.slice(0, MAX_DROPDOWN_RESULTS).map((u) => (
                    <button
                      key={u.id}
                      className="w-full flex items-center gap-2 px-3.5 py-2.5 text-[0.8125rem] text-left hover:bg-[var(--bg-soft)] transition-colors"
                      style={{ color: "var(--ink-2)" }}
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => {
                        setUserIds((ids) => [...ids, u.id]);
                        setUserSearch("");
                      }}
                    >
                      <PlusIcon style={{ width: 14, height: 14, flexShrink: 0, color: "var(--ink-4)" }} />
                      {userLabel(u)}
                    </button>
                  ))}
                  {availableUsers.length > MAX_DROPDOWN_RESULTS && (
                    <div className="px-3.5 py-2 text-[0.75rem]" style={{ color: "var(--ink-4)" }}>
                      Keep typing to narrow — {availableUsers.length - MAX_DROPDOWN_RESULTS} more
                    </div>
                  )}
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
