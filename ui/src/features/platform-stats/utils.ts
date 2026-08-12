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

export const PLATFORM_OPTIONS: { value: AgentPlatform; label: string }[] = [
  { value: "slack", label: "Slack" },
  { value: "teams", label: "Teams" },
  { value: "telegram", label: "Telegram" },
];
