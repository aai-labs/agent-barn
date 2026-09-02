"use client";

import { useCallback, useEffect, useMemo } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

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

export function useStatsUrlState() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const state: StatsUrlState = useMemo(() => {
    const fallback = defaultWindow();
    const from = readInstant(searchParams.get("from"));
    const to = readInstant(searchParams.get("to"));
    const platform = AgentPlatformSchema.safeParse(searchParams.get("app"));
    const direction = MessageDirectionSchema.safeParse(searchParams.get("direction"));

    return {
      from: from ?? fallback.from,
      to: to ?? fallback.to,
      organizationId: searchParams.get("org"),
      platform: platform.success ? platform.data : null,
      direction: direction.success ? direction.data : "all",
    };
  }, [searchParams]);

  const write = useCallback(
    (next: Partial<StatsUrlState>) => {
      const merged = { ...state, ...next };
      const params = new URLSearchParams();
      params.set("from", merged.from);
      params.set("to", merged.to);
      if (merged.organizationId) params.set("org", merged.organizationId);
      if (merged.platform) params.set("app", merged.platform);
      if (merged.direction !== "all") params.set("direction", merged.direction);
      router.replace(`${pathname}?${params.toString()}`, { scroll: false });
    },
    [router, pathname, state],
  );

  const hasBounds = searchParams.has("from") && searchParams.has("to");
  useEffect(() => {
    if (!hasBounds) write({});
  }, [hasBounds, write]);

  return { state, write };
}
