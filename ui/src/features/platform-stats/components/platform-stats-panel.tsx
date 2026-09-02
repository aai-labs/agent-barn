"use client";

import { useMemo } from "react";

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
import { usePlatformOrganization } from "@/features/organizations/hooks/use-platform-organization";

import {
  usePlatformAgentStats,
  usePlatformMessageStats,
} from "../hooks/use-platform-stats";
import { useStatsUrlState } from "../hooks/use-stats-url-state";
import { perBucketLabel, withinLabel } from "../format";
import type {
  AgentPlatform,
  MessageDirection,
  StatsFilters,
  StatsRange,
} from "../schemas";
import { DIRECTION_OPTIONS, MESSAGING_APP_OPTIONS, maskDirection } from "../utils";
import { AgentsChart } from "./agents-chart";
import { MessagesChart } from "./messages-chart";

const MAX_RANGE_DAYS = 366;

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
          data-testid={`stat-tile-${label}`}
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
  const { state, write } = useStatsUrlState();

  const filters: StatsFilters = useMemo(
    () => ({
      organizationId: state.organizationId ?? undefined,
      platform: state.platform ?? undefined,
    }),
    [state.organizationId, state.platform],
  );

  // Memoised because the range is part of the query key: a fresh object on
  // every render means a new key every render, which refetches in a loop.
  const range: StatsRange = useMemo(
    () => ({ fromDate: state.from, toDate: state.to }),
    [state.from, state.to],
  );

  const { organization } = usePlatformOrganization(state.organizationId ?? "");

  const messages = usePlatformMessageStats(filters, range);
  const agents = usePlatformAgentStats(filters, range);

  const counts = useMemo(() => {
    if (!messages.stats) return null;
    const { inbound, outbound } = maskDirection(messages.stats, state.direction);
    return { inbound, outbound, total: inbound + outbound };
  }, [messages.stats, state.direction]);

  const messageSeries = useMemo(
    () => (messages.stats?.series ?? []).map((p) => maskDirection(p, state.direction)),
    [messages.stats, state.direction],
  );
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
            organizationId={state.organizationId}
            organizationName={organization?.name ?? null}
            onChange={(next) => write({ organizationId: next?.id ?? null })}
            className={CONTROL_CLASS}
            width=""
          />

          <Select
            value={state.platform ?? "__all__"}
            onValueChange={(v) =>
              write({ platform: v === "__all__" ? null : (v as AgentPlatform) })
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
            value={state.direction}
            onValueChange={(v) => write({ direction: v as MessageDirection })}
          >
            <SelectTrigger
              aria-label="Filter by direction"
              className={TRIGGER_CLASS}
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {DIRECTION_OPTIONS.map(({ value, label }) => (
                <SelectItem key={value} value={value}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <DateRangePicker
            from={state.from}
            to={state.to}
            onChange={(from, to) => write({ from, to })}
            ariaLabel="Reporting date range"
            maxRangeDays={MAX_RANGE_DAYS}
            className={CONTROL_CLASS}
            width=""
          />
        </div>
      </div>

      {/* Scoped to the selected period. */}
      <div
        className="grid gap-4 mb-5"
        style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}
      >
        <StatTile
          label="Messages"
          value={counts?.total ?? null}
          isLoading={messages.isLoading}
        />
        <StatTile
          label="Received"
          value={counts?.inbound ?? null}
          isLoading={messages.isLoading}
        />
        <StatTile
          label="Sent"
          value={counts?.outbound ?? null}
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
              series={messageSeries}
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
