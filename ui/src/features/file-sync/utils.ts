import { createQueryKeyStructure } from "@/shared/query-keys";
import { formatDate } from "@/shared/date";

import type { AgentFileSync, AgentFileSyncActivityEntry } from "./schemas";

export const fileSyncKey = createQueryKeyStructure("agent-file-sync");

export function agentFileSyncKey(organizationId: string, agentId: string) {
  return [...fileSyncKey.all, organizationId, agentId] as const;
}

export function fileSyncStatusKey(organizationId: string, agentId: string) {
  return [...agentFileSyncKey(organizationId, agentId), "status"] as const;
}

export function fileSyncActivityKey(organizationId: string, agentId: string) {
  return [...agentFileSyncKey(organizationId, agentId), "activity"] as const;
}

export type FileSyncSummary = { headline: string; detail: string | null };

export function fileSyncSummary(fileSync: AgentFileSync, agentStatus: string): FileSyncSummary {
  const provider = fileSync.provider?.displayName ?? "the storage provider";
  switch (fileSync.state) {
    case "synced": {
      const checked = fileSync.lastContactAt ? `Last checked ${formatDate(fileSync.lastContactAt)}.` : null;
      const stopped = agentStatus === "STOPPED" ? `The agent is stopped. Edits made in ${provider} are applied when it starts.` : null;
      return { headline: "Synced", detail: [checked, stopped].filter(Boolean).join(" ") || null };
    }
    case "waiting_for_restart":
      return { headline: "Starts syncing after the next restart", detail: null };
    case "turned_off":
      return { headline: "Turned off", detail: `Files aren't synced. The folder in ${provider} is kept.` };
    case "setting_up":
      return { headline: `Setting up the folder in ${provider}…`, detail: null };
    case "throttled":
      return {
        headline: `${provider} asked Agent Barn to slow down.`,
        detail: fileSync.retryAt ? `Edits made there are picked up again around ${formatDate(fileSync.retryAt)}.` : null,
      };
    case "not_syncing":
      return {
        headline: fileSync.lastContactAt
          ? `This agent hasn't checked in with sync since ${formatDate(fileSync.lastContactAt)}.`
          : "This agent hasn't checked in with sync.",
        detail: "Check its logs, or restart it.",
      };
    case "not_connected":
      return { headline: "Not connected", detail: null };
  }
}

export function fileSyncActivitySentence(entry: AgentFileSyncActivityEntry, providerName: string | null): string {
  const provider = providerName ?? "the storage provider";
  const path = entry.path ?? "A file";
  switch (entry.kind) {
    case "edit_undone":
      return `Someone edited ${path} in ${provider}. Agent Barn manages that file, so the agent's copy was put back.`;
    case "restored":
      return `${path} was deleted or moved away in ${provider}. The agent's copy was put back.`;
    case "renamed_back":
      return `${path} was renamed or moved in ${provider}. It was moved back.`;
    case "moved_not_synced":
      return `${path} was added in ${provider}. The agent doesn't use it, so it was moved to _Not synced.`;
    case "folder_restored":
      return `The agent's folder was renamed, moved or deleted in ${provider}. It was put back.`;
    case "conflict_agent_won":
      return `${path} changed in the agent and in ${provider} at the same time. The agent's version was kept; the other edit is in ${provider}'s version history.`;
    case "deleted_by_agent":
      return `The agent deleted ${path}, so it was deleted in ${provider} too.`;
    case "skipped_too_large":
      return `${path} is over 100 MB, so it isn't synced.`;
    case "skipped_name":
      return `${path} has a name or path ${provider} doesn't accept, so it isn't synced.`;
    case "skipped_no_space":
      return `The agent's disk was full, so an edit to ${path} couldn't be applied yet. It will be retried.`;
  }
}
