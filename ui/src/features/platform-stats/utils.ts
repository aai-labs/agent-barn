import { createQueryKeyStructure } from "@/shared/query-keys";

import type { AgentPlatform } from "./schemas";

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
