import { createQueryKeyStructure } from "@/shared/query-keys";
import { formatDate } from "@/shared/date";

import type { AgentFileSync } from "./schemas";

export const fileSyncKey = createQueryKeyStructure("agent-file-sync");

export function agentFileSyncKey(organizationId: string, agentId: string) {
  return [...fileSyncKey.all, organizationId, agentId] as const;
}

export function fileSyncStatusKey(organizationId: string, agentId: string) {
  return [...agentFileSyncKey(organizationId, agentId), "status"] as const;
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
