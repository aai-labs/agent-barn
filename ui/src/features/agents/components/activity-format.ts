import type { ActivityTrigger } from "../schemas";

export const TRIGGER_LABEL: Record<ActivityTrigger, string> = {
  user: "Nearby message",
  background: "No nearby message",
};

export const TRIGGER_HINT: Record<ActivityTrigger, string> = {
  user: "A message from a person arrived just before this work started.",
  background:
    "No message from a person was recorded nearby. Heartbeats, crons, webhook events, follow-ups, and missing telemetry cannot be distinguished.",
};

/** How often the agent wakes, as a sentence fragment. */
export function formatCadence(seconds: number): string {
  if (seconds < 90) return "about every minute";
  if (seconds < 3600) return `about every ${Math.round(seconds / 60)} minutes`;
  const hours = seconds / 3600;
  if (hours < 48) {
    const rounded = hours < 10 ? Math.round(hours * 10) / 10 : Math.round(hours);
    return `about every ${rounded} hour${rounded === 1 ? "" : "s"}`;
  }
  const days = Math.round(hours / 24);
  return `about every ${days} days`;
}

/** Wall-clock time for one row, in the reader's own timezone. */
export function formatClock(iso: string): string {
  const value = new Date(iso);
  const time = value.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
  const isToday = value.toDateString() === new Date().toDateString();
  if (isToday) return time;
  return `${value.toLocaleDateString("en-US", { month: "short", day: "numeric" })} ${time}`;
}

/** A wake's span, collapsed to a single instant when it lasted under a second. */
export function formatSpan(startedAt: string, endedAt: string): string | null {
  const seconds = Math.round((new Date(endedAt).getTime() - new Date(startedAt).getTime()) / 1000);
  if (seconds <= 0) return null;
  if (seconds < 60) return `${seconds}s`;
  return `${Math.round(seconds / 60)}m`;
}

/** The prompt size a wake sent per call, as a range when the calls differed. */
export function formatTokenRange(
  min: number,
  max: number,
  format: (value: number) => string,
): string {
  return min === max ? format(min) : `${format(min)}–${format(max)}`;
}
