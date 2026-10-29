import { formatBytes, formatCores } from "@/features/resource-usage/format";

import type {
  CapacityLevel,
  CapacityLine,
  EnvironmentSource,
  HealthLevel,
  SourceState,
  VolumeGroup,
} from "./schemas";

export const environmentHealthKey = {
  /** Platform data: no Organization's cache is its, so it is not under any Organization key. */
  all: ["platform", "environment-health"] as const,
};

/** The cluster changes faster than usage figures do, but a minute is enough for a status page. */
export const ENVIRONMENT_HEALTH_REFETCH_MS = 60_000;

export const SOURCE_LABELS: Record<EnvironmentSource, string> = {
  pods: "Pods",
  deployments: "Deployments",
  stateful_sets: "StatefulSets",
  volume_claims: "Volume claims",
  resource_quotas: "Resource quota",
  events: "Events",
  prometheus: "Monitoring",
};

/** Why a source is missing, in the words an administrator would act on. */
export const SOURCE_STATE_TEXT: Record<Exclude<SourceState, "available">, string> = {
  forbidden: "not permitted for the service account",
  unavailable: "could not be read",
  not_configured: "not set up in this environment",
};

export const VOLUME_GROUP_LABELS: Record<VolumeGroup, string> = {
  infrastructure: "Platform services",
  active_agents: "Running agents",
  stopped_agents: "Stopped agents",
  restore_points: "Restore points",
  orphaned: "Orphaned",
};

export type Tone = "ok" | "warn" | "err" | "muted";

export const TONE_COLOR: Record<Tone, string> = {
  ok: "var(--ok)",
  warn: "var(--warn)",
  err: "var(--err)",
  muted: "var(--ink-4)",
};

export function healthTone(level: HealthLevel): Tone {
  if (level === "critical") return "err";
  if (level === "warning") return "warn";
  if (level === "ok") return "ok";
  return "muted";
}

export function capacityTone(level: CapacityLevel): Tone {
  if (level === "critical" || level === "ceiling_out_of_date") return "err";
  if (level === "warning") return "warn";
  if (level === "ok") return "ok";
  return "muted";
}

/** A quota figure in the unit its line counts in. */
export function formatQuantity(value: number, unit: CapacityLine["unit"]): string {
  if (unit === "bytes") return formatBytes(value);
  if (unit === "cores") return `${formatCores(value)} cores`;
  return String(Math.round(value));
}

/** "just now", "5 min ago", "3 h ago", or the date once it is more than a day old. */
export function formatAgo(iso: string | null, now: Date = new Date()): string {
  if (!iso) return "—";
  const seconds = Math.max(0, (now.getTime() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)} h ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}
