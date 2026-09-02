"use client";

import { useEffect, useMemo, useState } from "react";

import { AppErrorState } from "@/components/app-error-state";
import { DateRangePicker } from "@/components/date-range-picker";
import { OrganizationCombobox } from "@/components/organization-combobox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useInfiniteOrganizations } from "@/features/organizations/hooks/use-infinite-organizations";

import {
  usePlatformAgentStats,
  usePlatformMessageStats,
} from "../hooks/use-platform-stats";
import { perBucketLabel, withinLabel } from "../format";
import { DEFAULT_PRESET, PRESETS, type PresetId, presetRange } from "../presets";
import type { AgentPlatform, StatsFilters, StatsRange } from "../schemas";
import { MESSAGING_APP_OPTIONS } from "../utils";
import { AgentsChart } from "./agents-chart";
import { MessagesChart } from "./messages-chart";

function StatTile({
  label,
  value,
  isLoading,
}: {
  label: string;
  value: number | null;
  isLoading: boolean;
}) {
  return (
    <div className="af-card px-5 py-[18px]">
      <div className="text-[13px] mb-1.5" style={{ color: "var(--ink-3)" }}>
        {label}
      </div>
      {isLoading ? (
        <div
          className="h-7 w-20 rounded-md animate-pulse"
          style={{ background: "var(--bg-soft)" }}
        />
      ) : (
        <div
          className="text-[26px] font-semibold tracking-tight leading-none"
          style={{ color: "var(--ink)" }}
        >
          {(value ?? 0).toLocaleString()}
        </div>
      )}
    </div>
  );
}

const CONTROL_CLASS =
  "af-card h-[33px] px-2.5 py-1.5 text-[12.5px] rounded-lg border-0 outline-none";

// Radix renders the trigger as a button; match the toolbar and keep the height
// identical to the combobox and date picker beside it.
// The Radix trigger sets its height through `data-[size=default]:h-8`, which
// outranks a plain height class — match the variant to win.
const TRIGGER_CLASS = `${CONTROL_CLASS} data-[size=default]:h-[33px] gap-2 font-normal shadow-none focus-visible:ring-0`;

export function PlatformStatsPanel() {
  const [preset, setPreset] = useState<PresetId>(DEFAULT_PRESET);
  const [filters, setFilters] = useState<StatsFilters>({});
  const [custom, setCustom] = useState<{ from: string; to: string }>({ from: "", to: "" });
  // The combobox shows a name, the API takes an id, so both are tracked.
  const [org, setOrg] = useState<{ id: string; name: string } | null>(null);

  const [minute, setMinute] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setMinute(Date.now()), 60_000);
    return () => clearInterval(timer);
  }, []);

  const isCustom = preset === "custom";
  // Memoised because the range is part of the query key: a fresh object with a
  // fresh `now` on every render means a new key every render, which refetches
  // in a loop. Only a preset, date or minute change should move it.
  const range: StatsRange = useMemo(() => {
    if (!isCustom) return presetRange(preset, new Date(minute)) ?? {};
    // The picker hands back local start-of-day / end-of-day already.
    return {
      fromDate: custom.from || undefined,
      toDate: custom.to || undefined,
    };
  }, [isCustom, preset, minute, custom.from, custom.to]);

  const messages = usePlatformMessageStats(filters, range);
  const agents = usePlatformAgentStats(filters, range);
  // pageSize 1 because only the total is wanted here — the combobox pages the
  // list itself. This replaces eagerly fetching 200 Organizations for a count.
  const { total: organizationCount, isLoading: orgsLoading } =
    useInfiniteOrganizations({ pageSize: 1 });

  const error = messages.error ?? agents.error;
  if (error) {
    return (
      <AppErrorState
        error={error}
        title="We couldn't load platform stats"
        description="The stats endpoints are unavailable right now."
        onRetry={() => {
          void messages.refetch();
          void agents.refetch();
        }}
        retryLabel="Retry"
        className="min-h-[12rem] mb-10"
      />
    );
  }

  return (
    <div className="mb-10">
      {/* Point-in-time, and deliberately above the period controls: these read
          the Agent's current state and do not move with the period. Sitting
          among the period-scoped tiles they read as a contradiction — a
          one-hour window can show zero active against three hundred running. */}
      <div className="mb-8">
        <div className="mb-5">
          <h2
            className="text-[19px] font-semibold tracking-tight m-0"
            style={{ color: "var(--ink)" }}
          >
            Overview
          </h2>
          <p className="mt-1.5 text-[13.5px]" style={{ color: "var(--ink-3)" }}>
            Current counts. Agent totals follow the filters below; the
            Organization count is platform-wide.
          </p>
        </div>
        <div
          className="grid gap-4"
          style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}
        >
          <StatTile
            label="Organizations"
            value={organizationCount}
            isLoading={orgsLoading}
          />
          <StatTile
            label="Agents"
            value={agents.stats?.total ?? null}
            isLoading={agents.isLoading}
          />
          <StatTile
            label="Running"
            value={agents.stats?.running ?? null}
            isLoading={agents.isLoading}
          />
          <StatTile
            label="Stopped"
            value={agents.stats?.stopped ?? null}
            isLoading={agents.isLoading}
          />
          <StatTile
            label="Errored"
            value={agents.stats?.errored ?? null}
            isLoading={agents.isLoading}
          />
        </div>
      </div>

      <div className="flex items-end justify-between flex-wrap gap-3 mb-5">
        <div>
          <h2
            className="text-[19px] font-semibold tracking-tight m-0"
            style={{ color: "var(--ink)" }}
          >
            Activity
          </h2>
          <p className="mt-1.5 text-[13.5px]" style={{ color: "var(--ink-3)" }}>
            Messages handled and agents doing work over the selected period.
          </p>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <OrganizationCombobox
            organizationId={org?.id ?? null}
            organizationName={org?.name ?? null}
            onChange={(next) => {
              setOrg(next);
              setFilters((f) => ({ ...f, organizationId: next?.id }));
            }}
            className={CONTROL_CLASS}
            width=""
          />

          <Select
            value={filters.platform ?? "__all__"}
            onValueChange={(v) =>
              setFilters((f) => ({
                ...f,
                platform: v === "__all__" ? undefined : (v as AgentPlatform),
              }))
            }
          >
            <SelectTrigger
              aria-label="Filter by messaging app"
              className={TRIGGER_CLASS}
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__all__">All messaging apps</SelectItem>
              {MESSAGING_APP_OPTIONS.map(({ value, label }) => (
                <SelectItem key={value} value={value}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select
            value={preset}
            onValueChange={(v) => setPreset(v as PresetId)}
          >
            <SelectTrigger
              aria-label="Reporting period"
              className={TRIGGER_CLASS}
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PRESETS.map(({ id, label }) => (
                <SelectItem key={id} value={id}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          {isCustom && (
            <DateRangePicker
              from={custom.from}
              to={custom.to}
              onChange={(from, to) => setCustom({ from, to })}
              placeholder="Pick a range"
              className={CONTROL_CLASS}
              width=""
            />
          )}
        </div>
      </div>

      {/* Scoped to the selected period. */}
      <div
        className="grid gap-4 mb-5"
        style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}
      >
        <StatTile
          label="Messages"
          value={messages.stats?.total ?? null}
          isLoading={messages.isLoading}
        />
        <StatTile
          label="Received"
          value={messages.stats?.inbound ?? null}
          isLoading={messages.isLoading}
        />
        <StatTile
          label="Sent"
          value={messages.stats?.outbound ?? null}
          isLoading={messages.isLoading}
        />
        <StatTile
          label="Active agents"
          value={agents.stats?.active ?? null}
          isLoading={agents.isLoading}
        />
      </div>

      <div className="flex flex-col gap-4">
        <div className="af-card px-5 py-[18px]">
          <div
            className="text-[13px] mb-3"
            style={{ color: "var(--ink-3)" }}
          >
            {perBucketLabel("Messages", messages.stats?.granularity ?? "day")}
          </div>
          {messages.isLoading ? (
            <div
              className="h-[220px] rounded-md animate-pulse"
              style={{ background: "var(--bg-soft)" }}
            />
          ) : (
            <MessagesChart
              series={messages.stats?.series ?? []}
              granularity={messages.stats?.granularity ?? "day"}
            />
          )}
        </div>

        <div className="af-card px-5 py-[18px]">
          <div
            className="text-[13px] mb-3"
            style={{ color: "var(--ink-3)" }}
          >
            Agents over time
          </div>
          <p className="text-[12px] mb-2" style={{ color: "var(--ink-4)" }}>
            Active means the agent sent or received a message, or ran a tool,{" "}
            {withinLabel(agents.stats?.granularity ?? "day")}.
          </p>
          {agents.isLoading ? (
            <div
              className="h-[200px] rounded-md animate-pulse"
              style={{ background: "var(--bg-soft)" }}
            />
          ) : (
            <AgentsChart
              series={agents.stats?.series ?? []}
              granularity={agents.stats?.granularity ?? "day"}
            />
          )}
        </div>
      </div>
    </div>
  );
}
