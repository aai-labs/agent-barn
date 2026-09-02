import type { StatsRange } from "./schemas";

export type PresetId =
  | "lastHour"
  | "last6h"
  | "last12h"
  | "thisWeek"
  | "thisMonth"
  | "thisYear"
  | "custom";

// Boundaries are computed in the viewer's local timezone, because "this month"
// means their month. They are sent as absolute instants, so the server still
// buckets in UTC — near midnight a bucket label can therefore sit on the
// adjacent UTC day even though the totals are right.
function startOfDay(d: Date): Date {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x;
}

function addHours(d: Date, n: number): Date {
  return new Date(d.getTime() + n * 3600_000);
}

function addDays(d: Date, n: number): Date {
  const x = new Date(d);
  x.setDate(x.getDate() + n);
  return x;
}

function startOfWeek(d: Date): Date {
  const x = startOfDay(d);
  // Monday-first: getDay() is 0 for Sunday.
  const offset = (x.getDay() + 6) % 7;
  return addDays(x, -offset);
}

function iso(d: Date): string {
  return d.toISOString();
}

/** `end`, nudged so an open-ended preset is never zero-width. */
function atLeastAMinuteAfter(start: Date, end: Date): Date {
  const floor = new Date(start.getTime() + 60_000);
  return end > floor ? end : floor;
}

/**
 * `now` floored to the minute.
 *
 * The open-ended presets end at "now", and that value becomes part of the
 * query key. Taken at millisecond resolution it differs on every render, so
 * the key never repeats and the query refetches forever. Flooring makes the
 * key stable within a minute; the useMemo at the call site keeps it stable
 * across renders regardless.
 */
function nowFloored(now: Date): Date {
  const x = new Date(now);
  x.setSeconds(0, 0);
  return x;
}

export const PRESETS: { id: PresetId; label: string }[] = [
  { id: "lastHour", label: "Last hour" },
  { id: "last6h", label: "Last 6 hours" },
  { id: "last12h", label: "Last 12 hours" },
  { id: "thisWeek", label: "This week" },
  { id: "thisMonth", label: "This month" },
  { id: "thisYear", label: "This year" },
  { id: "custom", label: "Custom range" },
];

export const DEFAULT_PRESET: PresetId = "thisMonth";

/** Absolute [from, to) bounds for a preset, or null for `custom`. */
export function presetRange(id: PresetId, at: Date = new Date()): StatsRange | null {
  const now = nowFloored(at);

  switch (id) {
    case "lastHour":
      return { fromDate: iso(addHours(now, -1)), toDate: iso(now) };
    case "last6h":
      return { fromDate: iso(addHours(now, -6)), toDate: iso(now) };
    case "last12h":
      return { fromDate: iso(addHours(now, -12)), toDate: iso(now) };
    case "thisWeek": {
      const weekStart = startOfWeek(now);
      return { fromDate: iso(weekStart), toDate: iso(atLeastAMinuteAfter(weekStart, now)) };
    }
    case "thisMonth": {
      const monthStart = new Date(now.getFullYear(), now.getMonth(), 1);
      return { fromDate: iso(monthStart), toDate: iso(atLeastAMinuteAfter(monthStart, now)) };
    }
    case "thisYear": {
      const yearStart = new Date(now.getFullYear(), 0, 1);
      return { fromDate: iso(yearStart), toDate: iso(atLeastAMinuteAfter(yearStart, now)) };
    }
    case "custom":
      return null;
  }
}
