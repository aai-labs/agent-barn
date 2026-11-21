import type { AnomalySignal, RateSignal, Sensitivity } from "./schemas";

export const anomaliesKey = {
  all: ["anomalies"] as const,
  detection: (organizationId: string) => ["anomalies", "detection", organizationId] as const,
  agent: (organizationId: string, agentId: string) => ["anomalies", "agent", organizationId, agentId] as const,
  list: (organizationId: string, agentId: string) =>
    ["anomalies", "agent", organizationId, agentId, "list"] as const,
  normal: (organizationId: string, agentId: string) =>
    ["anomalies", "agent", organizationId, agentId, "normal"] as const,
};

/** Agents need activity on this many different days before anything is flagged. */
export const MIN_ACTIVE_DAYS = 3;
export const BASELINE_DAYS = 14;

export const SIGNAL_LABELS: Record<AnomalySignal, string> = {
  LLM_TOKENS_PER_HOUR: "Model tokens per hour",
  LLM_CALLS_PER_HOUR: "Model calls per hour",
  TOOL_CALLS_PER_HOUR: "Tool calls per hour",
  TOOL_ERROR_RATE: "Failed tool calls",
  LLM_ERROR_RATE: "Failed model calls",
  WRITES_PER_HOUR: "Changes and deletions per hour",
  LLM_TOKENS_CAP: "Over the hourly token cap",
  LLM_CALLS_CAP: "Over the hourly model call cap",
  NEW_TOOL: "New tool",
  NEW_INTEGRATION: "New integration",
  NEW_INTEGRATION_ACTION: "New action on an integration",
  NEW_DESTINATION: "New destination",
};

export const SENSITIVITY_LABELS: Record<Sensitivity, string> = {
  LOW: "Low",
  NORMAL: "Normal",
  HIGH: "High",
};

export const SENSITIVITY_HINTS: Record<Sensitivity, string> = {
  LOW: "Flags only large jumps.",
  NORMAL: "Flags clear jumps from what is usual.",
  HIGH: "Flags smaller jumps too, so expect more to review.",
};

const FIRST_USE: ReadonlySet<AnomalySignal> = new Set([
  "NEW_TOOL",
  "NEW_INTEGRATION",
  "NEW_INTEGRATION_ACTION",
  "NEW_DESTINATION",
]);

export function isFirstUse(signal: AnomalySignal): boolean {
  return FIRST_USE.has(signal);
}

export function formatSignalValue(signal: AnomalySignal | RateSignal, value: number): string {
  if (signal === "TOOL_ERROR_RATE" || signal === "LLM_ERROR_RATE") return `${Math.round(value * 100)}%`;
  return Math.round(value).toLocaleString("en-US");
}

/** A positive whole number, empty for none, or an error to show next to the field. */
// The largest cap the server keeps.
const MAX_CAP = 2_147_483_647;

export function parseCap(value: string): { cap: number | null; error: string | null } {
  const trimmed = value.trim().replace(/,/g, "");
  if (trimmed === "") return { cap: null, error: null };
  if (!/^\d+$/.test(trimmed) || Number(trimmed) <= 0 || Number(trimmed) > MAX_CAP) {
    return {
      cap: null,
      error: `Enter a whole number from 1 to ${MAX_CAP.toLocaleString("en-US")}, or leave it empty for no cap.`,
    };
  }
  return { cap: Number(trimmed), error: null };
}
