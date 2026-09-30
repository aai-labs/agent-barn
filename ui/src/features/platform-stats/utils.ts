import { createQueryKeyStructure } from "@/shared/query-keys";

import type { AgentPlatform, MessageDirection } from "./schemas";

export const platformStatsKey = createQueryKeyStructure("platform-stats");

// "Platform" is taken on this page — Platform View, Platform Administrator,
// platform stats — so this axis is called the messaging app in the UI. The API
// field stays `platform`, matching the Communication Connection model.
export const MESSAGING_APP_OPTIONS: { value: AgentPlatform; label: string }[] = [
  { value: "slack", label: "Slack" },
  { value: "teams", label: "Teams" },
  { value: "telegram", label: "Telegram" },
  { value: "discord", label: "Discord" },
];

export const DIRECTION_OPTIONS: { value: MessageDirection; label: string }[] = [
  { value: "all", label: "All messages" },
  { value: "inbound", label: "Received only" },
  { value: "outbound", label: "Sent only" },
];

/** Zeroes whichever direction is out of scope. */
export function maskDirection<T extends { inbound: number; outbound: number }>(
  point: T,
  direction: MessageDirection,
): T {
  return {
    ...point,
    inbound: direction === "outbound" ? 0 : point.inbound,
    outbound: direction === "inbound" ? 0 : point.outbound,
  };
}
