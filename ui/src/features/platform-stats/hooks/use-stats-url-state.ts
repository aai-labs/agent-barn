"use client";

import { useCallback, useEffect, useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";

import {
  type AgentPlatform,
  AgentPlatformSchema,
  type MessageDirection,
  MessageDirectionSchema,
} from "../schemas";

const DEFAULT_WINDOW_DAYS = 30;

export interface StatsUrlState {
  from: string;
  to: string;
  organizationId: string | null;
  platform: AgentPlatform | null;
  direction: MessageDirection;
}

function startOfDayIso(date: Date): string {
  const start = new Date(date);
  start.setHours(0, 0, 0, 0);
  return start.toISOString();
}

function endOfDayIso(date: Date): string {
  const end = new Date(date);
  end.setHours(23, 59, 59, 999);
  return end.toISOString();
}

/** Local-day bounds covering today and the previous `DEFAULT_WINDOW_DAYS - 1` days. */
export function defaultWindow(at: Date = new Date()): { from: string; to: string } {
  const start = new Date(at);
  start.setDate(start.getDate() - (DEFAULT_WINDOW_DAYS - 1));
  return { from: startOfDayIso(start), to: endOfDayIso(at) };
}

function readInstant(raw: string | null): string | null {
  if (!raw) return null;
  return Number.isNaN(new Date(raw).getTime()) ? null : raw;
}

function parse(params: URLSearchParams): StatsUrlState {
  const fallback = defaultWindow();
  const platform = AgentPlatformSchema.safeParse(params.get("app"));
  const direction = MessageDirectionSchema.safeParse(params.get("direction"));

  return {
    from: readInstant(params.get("from")) ?? fallback.from,
    to: readInstant(params.get("to")) ?? fallback.to,
    organizationId: params.get("org"),
    platform: platform.success ? platform.data : null,
    direction: direction.success ? direction.data : "all",
  };
}

function toQuery(state: StatsUrlState): string {
  const params = new URLSearchParams();
  params.set("from", state.from);
  params.set("to", state.to);
  if (state.organizationId) params.set("org", state.organizationId);
  if (state.platform) params.set("app", state.platform);
  if (state.direction !== "all") params.set("direction", state.direction);
  return params.toString();
}

/**
 * Panel state, seeded from the query string and mirrored back to it.
 *
 * State is local and authoritative. The URL is written with the History API
 * rather than `router.replace`, which would navigate: on a prerendered route
 * `useSearchParams` does not observe that write, so anything waiting to read
 * its own value back never settles.
 */
export function useStatsUrlState() {
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const [state, setState] = useState<StatsUrlState>(() => parse(searchParams));

  useEffect(() => {
    window.history.replaceState(null, "", `${pathname}?${toQuery(state)}`);
  }, [pathname, state]);

  const write = useCallback(
    (next: Partial<StatsUrlState>) => setState((prev) => ({ ...prev, ...next })),
    [],
  );

  return { state, write };
}
