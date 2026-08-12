"use client";

import { useMemo, useState } from "react";

import { AppErrorState } from "@/components/app-error-state";
import { useAllOrganizations } from "@/features/organizations/hooks/use-all-organizations";

import {
  usePlatformAgentStats,
  usePlatformMessageStats,
} from "../hooks/use-platform-stats";
import { perBucketLabel, withinLabel } from "../format";
import { DEFAULT_PRESET, PRESETS, type PresetId, presetRange } from "../presets";
import type { AgentPlatform, StatsFilters, StatsRange } from "../schemas";
import { PLATFORM_OPTIONS } from "../utils";
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

// Native selects paint their arrow hard against the right edge, ignoring
// padding. appearance-none plus an inline chevron puts it back inside the
// control's own padding.
const CHEVRON =
  "url(\"data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%23888' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E\")";

const CONTROL_CLASS =
  "af-card px-2.5 py-1.5 text-[12.5px] rounded-lg border-0 outline-none";

const SELECT_CLASS = `${CONTROL_CLASS} appearance-none pr-7`;

const SELECT_STYLE: React.CSSProperties = {
  color: "var(--ink)",
  backgroundImage: CHEVRON,
  backgroundRepeat: "no-repeat",
  backgroundPosition: "right 0.6rem center",
};

export function PlatformStatsPanel() {
  const [preset, setPreset] = useState<PresetId>(DEFAULT_PRESET);
  const [filters, setFilters] = useState<StatsFilters>({});
  const [custom, setCustom] = useState<{ from?: string; to?: string }>({});

  const isCustom = preset === "custom";
  // Memoised because the range is part of the query key: a fresh object with a
  // fresh `now` on every render means a new key every render, which refetches
  // in a loop. Only a preset or date change should move it.
  const range: StatsRange = useMemo(() => {
    if (!isCustom) return presetRange(preset) ?? {};
    // Bare `yyyy-mm-dd` from the date inputs becomes a local-day span, matching
    // how the presets are computed.
    return {
      fromDate: custom.from ? new Date(`${custom.from}T00:00:00`).toISOString() : undefined,
      toDate: custom.to ? new Date(`${custom.to}T23:59:59.999`).toISOString() : undefined,
    };
  }, [isCustom, preset, custom.from, custom.to]);

  const messages = usePlatformMessageStats(filters, range);
  const agents = usePlatformAgentStats(filters, range);
  const { organizations, total: organizationCount, isLoading: orgsLoading } =
    useAllOrganizations({ enabled: true });

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
            Current counts, narrowed by the filters below.
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
          <select
            aria-label="Filter by organization"
            className={SELECT_CLASS}
            style={SELECT_STYLE}
            value={filters.organizationId ?? ""}
            onChange={(e) =>
              setFilters((f) => ({
                ...f,
                organizationId: e.target.value || undefined,
              }))
            }
          >
            <option value="">All organizations</option>
            {organizations.map((org) => (
              <option key={org.id} value={org.id}>
                {org.name}
              </option>
            ))}
          </select>

          <select
            aria-label="Filter by chat platform"
            className={SELECT_CLASS}
            style={SELECT_STYLE}
            value={filters.platform ?? ""}
            onChange={(e) =>
              setFilters((f) => ({
                ...f,
                platform: (e.target.value || undefined) as
                  | AgentPlatform
                  | undefined,
              }))
            }
          >
            <option value="">All platforms</option>
            {PLATFORM_OPTIONS.map(({ value, label }) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>

          <select
            aria-label="Reporting period"
            className={SELECT_CLASS}
            style={SELECT_STYLE}
            value={preset}
            onChange={(e) => setPreset(e.target.value as PresetId)}
          >
            {PRESETS.map(({ id, label }) => (
              <option key={id} value={id}>
                {label}
              </option>
            ))}
          </select>

          {isCustom && (
            <div className="flex items-center gap-1.5">
              <input
                type="date"
                aria-label="From date"
                className={CONTROL_CLASS}
                style={{ color: "var(--ink)" }}
                value={custom.from ?? ""}
                max={custom.to}
                onChange={(e) =>
                  setCustom((c) => ({ ...c, from: e.target.value || undefined }))
                }
              />
              <span className="text-[12px]" style={{ color: "var(--ink-4)" }}>
                to
              </span>
              <input
                type="date"
                aria-label="To date"
                className={CONTROL_CLASS}
                style={{ color: "var(--ink)" }}
                value={custom.to ?? ""}
                min={custom.from}
                onChange={(e) =>
                  setCustom((c) => ({ ...c, to: e.target.value || undefined }))
                }
              />
            </div>
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
