import { createQueryKeyStructure } from "@/shared/query-keys";

import type { AgentActivity, AgentValue } from "./schemas";

const UNATTRIBUTED_LABEL = "Unattributed";
const DELETED_AGENT_LABEL = "Deleted agent";
const UNATTRIBUTED_ROW_KEY = "unattributed";

export const organizationValueKey = createQueryKeyStructure("organization-value");
export const organizationActivityKey = createQueryKeyStructure("organization-activity");
export const valueSettingsKey = createQueryKeyStructure("value-settings");

export type KpiWindow = {
  fromDate?: string;
  toDate?: string;
};

export function windowQuery(range: KpiWindow): string {
  const params = new URLSearchParams();
  if (range.fromDate) params.set("from_date", range.fromDate);
  if (range.toDate) params.set("to_date", range.toDate);
  const query = params.toString();
  return query ? `?${query}` : "";
}

export type AgentKpiRow = {
  key: string;
  name: string;
  deleted: boolean;
  value: AgentValue | null;
  activity: AgentActivity | null;
};

export function mergeAgentRows(
  valueAgents: AgentValue[],
  activityAgents: AgentActivity[],
): AgentKpiRow[] {
  const rows = new Map<string, AgentKpiRow>();
  const rowFor = (agentId: string | null) => {
    const key = agentId ?? UNATTRIBUTED_ROW_KEY;
    const existing = rows.get(key);
    if (existing) return existing;
    const created: AgentKpiRow = { key, name: "", deleted: false, value: null, activity: null };
    rows.set(key, created);
    return created;
  };
  for (const agent of valueAgents) rowFor(agent.agentId).value = agent;
  for (const agent of activityAgents) rowFor(agent.agentId).activity = agent;

  return [...rows.values()].map((row) => {
    const unattributed = row.key === UNATTRIBUTED_ROW_KEY;
    return {
      ...row,
      name: unattributed
        ? UNATTRIBUTED_LABEL
        : (row.value?.agentName ?? row.activity?.agentName ?? DELETED_AGENT_LABEL),
      deleted: !unattributed && Boolean(row.value?.agentDeleted || row.activity?.agentDeleted),
    };
  });
}

export function outcomeTypeLabel(outcomeType: string): string {
  const words = outcomeType.toLowerCase().replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function costsHref(orgBase: string, from: string, to: string): string {
  const params = new URLSearchParams();
  if (from) params.set("from", from);
  if (to) params.set("to", to);
  const query = params.toString();
  return query ? `${orgBase}/costs?${query}` : `${orgBase}/costs`;
}
