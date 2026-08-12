import { createQueryKeyStructure } from "@/shared/query-keys";

import type { AgentPlatform, StatsPeriod } from "./schemas";

export const platformStatsKey = createQueryKeyStructure("platform-stats");

export const PERIOD_OPTIONS: { value: StatsPeriod; label: string }[] = [
  { value: "SEVEN_DAYS", label: "7d" },
  { value: "THIRTY_DAYS", label: "30d" },
  { value: "NINETY_DAYS", label: "90d" },
];

export const DEFAULT_PERIOD: StatsPeriod = "THIRTY_DAYS";

export const PERIOD_LABEL: Record<StatsPeriod, string> = {
  SEVEN_DAYS: "7 days",
  THIRTY_DAYS: "30 days",
  NINETY_DAYS: "90 days",
};

// "Platform" is taken on this page — Platform View, Platform Administrator,
// platform stats — so the Slack/Teams/Telegram axis is called the messaging
// app in the UI. The API field stays `platform`, matching the Agent model.
export const MESSAGING_APP_OPTIONS: { value: AgentPlatform; label: string }[] = [
  { value: "slack", label: "Slack" },
  { value: "teams", label: "Teams" },
  { value: "telegram", label: "Telegram" },
];
