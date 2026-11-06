"use client";

import { parseAsString, useQueryStates } from "nuqs";

import type { UsageDates } from "../utils";

// Not `from` and `to`: the Agent page's Costs and Activity tabs keep theirs there, and
// their windows may reach further back than the 15 days usage can.
const DATE_PARSERS = { usageFrom: parseAsString.withDefault(""), usageTo: parseAsString.withDefault("") };

/** The days a resource usage page is set to, kept in the query string. */
export function useUsageDates(): readonly [UsageDates, (from: string, to: string) => void] {
  const [params, setParams] = useQueryStates(DATE_PARSERS, { scroll: false, history: "replace" });
  const dates = { from: params.usageFrom, to: params.usageTo };
  const pick = (from: string, to: string) => void setParams({ usageFrom: from || null, usageTo: to || null });
  return [dates, pick] as const;
}
