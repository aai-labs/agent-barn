import { createQueryKeyStructure } from "@/shared/query-keys";

import type { AgentPlatform } from "./schemas";

export const platformStatsKey = createQueryKeyStructure("platform-stats");

// "Platform" is taken on this page — Platform View, Platform Administrator,
// platform stats — so the Slack/Telegram/Discord axis is called the messaging
// app in the UI. The API field stays `platform`, matching the Agent model.
export const MESSAGING_APP_OPTIONS: { value: AgentPlatform; label: string }[] = [
  { value: "slack", label: "Slack" },
  { value: "telegram", label: "Telegram" },
  { value: "discord", label: "Discord" },
];
