"use client";

import { useState, type ReactNode } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { AlertTriangle } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { DateRangePicker } from "@/components/date-range-picker";
import { Skeleton } from "@/components/ui/skeleton";
import { formatSpend, formatTokens } from "@/features/costs/format";
import { useCostUrlFilters } from "@/features/costs/hooks/use-cost-url-filters";
import { formatBucketLong } from "@/features/platform-stats/format";
import type { Granularity } from "@/features/platform-stats/schemas";
import { ApiError } from "@/shared/api/error/errors";

import {
  ACTIVITY_CALLS_PAGE_SIZE,
  WAKES_PAGE_SIZE,
  useAgentActivity,
  useAgentActivityCalls,
  useAgentWakes,
} from "../hooks/use-agent-activity";
import type {
  ActivityBucket,
  ActivityTrigger,
  ActivityTriggerBreakdown,
  Agent,
  AgentActivitySummary,
  AgentWake,
} from "../schemas";
import { canAgent } from "../utils";
import { TRIGGER_LABEL, formatCadence, formatClock } from "./activity-format";
import { ByPeriodTable, CallsTable, TableSkeleton, WakesTable } from "./activity-tables";
import { Pagination } from "./pagination";
import { RuntimeDiagnostics } from "./runtime-diagnostics";

// Stable reference: the hook reads its keys from this object's shape.
const ACTIVITY_FILTER_DEFAULTS = {
  from: "",
  to: "",
  trigger: "",
  focusFrom: "",
  focusTo: "",
};

const BUCKET_MS: Record<Granularity, number> = {
  minute: 60_000,
  hour: 3_600_000,
  day: 86_400_000,
  week: 604_800_000,
};

const CALLS_ANCHOR = "agent-activity-calls";

/** Share of spend above which background work is the story on this page. */
const MOSTLY_BACKGROUND = 0.8;

export function ActivityTab({ agent }: { agent: Agent }) {
  // The tab is gated on activity.read, which the runtime diagnostics need on
  // their own. The usage sections also need cost.read, so a reader without it
  // still gets the runtime evidence instead of a page of 403s.
  if (!canAgent(agent, "cost.read")) return <RuntimeOnly agent={agent} />;
  return <ActivityUsage agent={agent} />;
}

function RuntimeOnly({ agent }: { agent: Agent }) {
  const params = useParams();
  const orgId = typeof params?.orgId === "string" ? params.orgId : null;

  return (
    <div className="flex flex-col gap-4">
      <div
        className="af-card p-4 text-[13px]"
        style={{ color: "var(--ink-4)" }}
        data-testid="agent-activity-usage-restricted"
      >
        Usage and spend for this agent need cost access, which you don&apos;t have.
      </div>
      <RuntimeDiagnostics agent={agent} orgId={orgId} lastCallAt={null} usageAvailable={false} />
    </div>
  );
}

function ActivityUsage({ agent }: { agent: Agent }) {
  const [filters, setFilters] = useCostUrlFilters(ACTIVITY_FILTER_DEFAULTS);
  const [wakesPage, setWakesPage] = useState(1);
  const [callsPage, setCallsPage] = useState(1);

  const params = useParams();
  const orgId = typeof params?.orgId === "string" ? params.orgId : null;

  const activityWindow = {
    fromDate: filters.from || undefined,
    toDate: filters.to || undefined,
  };
  // The focus is a slice of the window: picking a period or a wake narrows
  // everything below it without changing what the summary describes.
  const focus = filters.focusFrom ? { fromDate: filters.focusFrom, toDate: filters.focusTo } : activityWindow;
  const trigger = (filters.trigger as ActivityTrigger | "") || "";

  const summary = useAgentActivity(agent.id, activityWindow);
  const wakes = useAgentWakes(agent.id, focus, trigger, wakesPage);
  const calls = useAgentActivityCalls(agent.id, focus, trigger, callsPage);

  function selectPeriod(bucket: ActivityBucket, granularity: Granularity) {
    const start = new Date(bucket.bucket).getTime();
    focusWithin(start, start + BUCKET_MS[granularity]);
  }

  function selectWake(wake: AgentWake) {
    // The window is half-open, so the last call needs a moment of room.
    focusWithin(new Date(wake.startedAt).getTime(), new Date(wake.endedAt).getTime() + 1000);
  }

  // A drill-down narrows, never widens. The summary covers [fromDate, toDate),
  // and the first and last buckets usually start before or end after it: their
  // counts above only include what falls inside, so the slice is cut to match.
  function focusWithin(start: number, end: number) {
    const summaryWindow = summary.data;
    const from = summaryWindow ? Math.max(start, Date.parse(summaryWindow.fromDate)) : start;
    const to = summaryWindow ? Math.min(end, Date.parse(summaryWindow.toDate)) : end;
    setFocus(new Date(from).toISOString(), new Date(to).toISOString());
  }

  function setFocus(from: string, to: string) {
    setFilters({ focusFrom: from, focusTo: to });
    setWakesPage(1);
    setCallsPage(1);
    document.getElementById(CALLS_ANCHOR)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function clearFocus() {
    setFilters({ focusFrom: null, focusTo: null });
    setWakesPage(1);
    setCallsPage(1);
  }

  function selectTrigger(next: ActivityTrigger | "") {
    setFilters({ trigger: next || null });
    setWakesPage(1);
    setCallsPage(1);
  }

  if (summary.error) {
    return (
      <div className="flex flex-col gap-4">
        <div className="af-card p-6 text-[13px]" style={{ color: "var(--ink-4)" }}>
          {summary.error instanceof ApiError && summary.error.status === 403
            ? "You don't have access to this agent's activity."
            : "We couldn't load this agent's activity."}
          <button className="af-btn af-btn-sm ml-3" onClick={() => void summary.refetch()}>Retry usage</button>
        </div>
        <RuntimeDiagnostics agent={agent} orgId={orgId} lastCallAt={null} usageAvailable={false} />
      </div>
    );
  }

  const data = summary.data;
  const windowLabel = data
    ? `${formatBucketLong(data.fromDate, "day")} – ${formatBucketLong(data.toDate, "day")}`
    : "Loading…";

  return (
    <div className="flex flex-col gap-4">
      <Section
        title="What this agent has been doing"
        description="Every billed model call, grouped into the bursts of work that produced them."
        action={
          <DateRangePicker
            from={filters.from}
            to={filters.to}
            onChange={(from, to) => {
              setFilters({ from: from || null, to: to || null, focusFrom: null, focusTo: null });
              setWakesPage(1);
              setCallsPage(1);
            }}
            placeholder={windowLabel}
            width="16rem"
            ariaLabel="Date range"
          />
        }
        testId="agent-activity-summary"
      >
        {!data ? (
          <Skeleton className="h-[92px] w-full" />
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Stat label="Spend" value={formatSpend(data.totals.spend)} />
              <Stat label="Model calls" value={data.totals.calls.toLocaleString("en-US")} />
              <Stat
                label="Wakes"
                value={data.totals.wakes.toLocaleString("en-US")}
                sub={data.wakeCadenceSeconds ? formatCadence(data.wakeCadenceSeconds) : undefined}
              />
              <Stat
                label="No nearby message"
                value={formatSpend(triggerOf(data, "background").spend)}
                sub={`${triggerOf(data, "background").calls.toLocaleString("en-US")} of ${data.totals.calls.toLocaleString("en-US")} calls`}
              />
            </div>
            <BackgroundCallout
              agentName={agent.name}
              summary={data}
              orgId={orgId}
              agentId={agent.id}
              onShowBackground={() => selectTrigger("background")}
            />
          </>
        )}
      </Section>

      <RuntimeDiagnostics agent={agent} orgId={orgId} lastCallAt={data?.lastCallAt ?? null} usageAvailable={!!data} />

      {data && data.totals.calls > 0 && (
        <Section
          title="Prompt size per call"
          description="Large prompts with little spread can suggest repeated context. Token counts alone cannot identify prompt contents or prove a cause."
          testId="agent-activity-prompt-size"
        >
          <div className="grid gap-3 sm:grid-cols-4">
            <Stat label="Average" value={formatTokens(data.promptTokensPerCall.avg)} />
            <Stat label="Median" value={formatTokens(data.promptTokensPerCall.median)} />
            <Stat label="95th percentile" value={formatTokens(data.promptTokensPerCall.p95)} />
            <Stat label="Largest" value={formatTokens(data.promptTokensPerCall.max)} />
          </div>
        </Section>
      )}

      <Section
        title="By period"
        description="Grouped in UTC. Press a call count to narrow everything below to that period."
        testId="agent-activity-by-period"
      >
        {!data ? (
          <TableSkeleton />
        ) : (
          <ByPeriodTable
            buckets={data.byBucket}
            granularity={data.granularity}
            onSelect={(bucket) => selectPeriod(bucket, data.granularity)}
          />
        )}
      </Section>

      <Section
        title="Wakes"
        description="Bursts grouped by timing. Message proximity suggests a trigger but does not prove it."
        action={<TriggerFilter value={trigger} onChange={selectTrigger} />}
        testId="agent-activity-wakes"
      >
        <FocusNote focusFrom={filters.focusFrom} focusTo={filters.focusTo} onClear={clearFocus} />
        {wakes.isPending ? (
          <TableSkeleton />
        ) : wakes.data ? (
          <>
            <WakesTable wakes={wakes.data.items} onSelect={selectWake} />
            <div className="mt-3">
              <Pagination
                page={wakesPage}
                totalPages={Math.ceil(wakes.data.total / WAKES_PAGE_SIZE)}
                onPageChange={setWakesPage}
                align="end"
              />
            </div>
          </>
        ) : (
          <AppErrorState
            error={wakes.error}
            title="We couldn't load this agent's wakes"
            onRetry={() => void wakes.refetch()}
            retryLabel="Retry wakes"
            className="min-h-0 p-0"
          />
        )}
      </Section>

      <div id={CALLS_ANCHOR} className="scroll-mt-4">
        <Section
          title="Calls"
          description="The individual requests behind the rows above."
          testId="agent-activity-calls"
        >
          <FocusNote focusFrom={filters.focusFrom} focusTo={filters.focusTo} onClear={clearFocus} />
          {calls.isPending ? (
            <TableSkeleton />
          ) : calls.data ? (
            <>
              <CallsTable calls={calls.data.items} />
              <div className="mt-3">
                <Pagination
                  page={callsPage}
                  totalPages={Math.ceil(calls.data.total / ACTIVITY_CALLS_PAGE_SIZE)}
                  onPageChange={setCallsPage}
                  align="end"
                />
              </div>
            </>
          ) : (
            <AppErrorState
              error={calls.error}
              title="We couldn't load this agent's calls"
              onRetry={() => void calls.refetch()}
              retryLabel="Retry calls"
              className="min-h-0 p-0"
            />
          )}
        </Section>
      </div>
    </div>
  );
}

function triggerOf(summary: AgentActivitySummary, trigger: ActivityTrigger): ActivityTriggerBreakdown {
  return (
    summary.byTrigger.find((entry) => entry.trigger === trigger) ?? {
      trigger,
      wakes: 0,
      calls: 0,
      spend: 0,
      promptTokens: 0,
    }
  );
}

/** The sentence this page exists to make possible. */
function BackgroundCallout({
  agentName,
  summary,
  orgId,
  agentId,
  onShowBackground,
}: {
  agentName: string;
  summary: AgentActivitySummary;
  orgId: string | null;
  agentId: string;
  onShowBackground: () => void;
}) {
  const background = triggerOf(summary, "background");
  const asked = triggerOf(summary, "user");
  if (background.calls === 0) return null;

  const share = summary.totals.spend > 0 ? background.spend / summary.totals.spend : 1;
  if (asked.calls > 0 && share < MOSTLY_BACKGROUND) return null;

  const headline =
    asked.calls === 0
      ? `No nearby messages recorded for ${agentName}`
      : `Most spend has no nearby recorded message`;
  const detail =
    asked.calls === 0
      ? `All ${background.calls.toLocaleString("en-US")} calls — ${formatSpend(background.spend)} across ${background.wakes.toLocaleString("en-US")} wakes — had no nearby recorded message to ${agentName}.`
      : `${Math.round(share * 100)}% of the spend — ${formatSpend(background.spend)} across ${background.wakes.toLocaleString("en-US")} wakes — had no nearby recorded message to ${agentName}.`;

  return (
    <div
      className="mt-4 flex flex-col gap-3 rounded-xl px-4 py-3.5 sm:flex-row sm:items-start"
      style={{
        border: "1px solid color-mix(in srgb, var(--warn) 30%, var(--line))",
        background: "var(--warn-soft)",
      }}
      data-testid="agent-activity-background-callout"
      role="status"
    >
      <AlertTriangle size={18} style={{ color: "var(--warn)", flexShrink: 0 }} className="mt-0.5" />
      <div className="min-w-0 flex-1">
        <div className="text-[0.9rem] font-semibold" style={{ color: "var(--ink)" }}>
          {headline}
        </div>
        <p className="mb-0 mt-1 text-[0.844rem] leading-relaxed" style={{ color: "var(--ink-3)" }}>
          {detail}
          {summary.wakeCadenceSeconds !== null && (
            <> It wakes {formatCadence(summary.wakeCadenceSeconds)}, between wake starts (median). This can suggest a schedule; it does not identify a heartbeat or cron.</>
          )}
        </p>
        <div className="mt-2.5 flex flex-wrap gap-2">
          <button type="button" className="af-btn af-btn-sm" onClick={onShowBackground}>
            Show only this work
          </button>
          {orgId && (
            <Link
              href={`/dashboard/${orgId}/agents/${agentId}/configuration?section=override`}
              className="af-btn af-btn-sm"
            >
              Review configuration
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}

function TriggerFilter({
  value,
  onChange,
}: {
  value: ActivityTrigger | "";
  onChange: (next: ActivityTrigger | "") => void;
}) {
  const options: [ActivityTrigger | "", string][] = [
    ["", "All"],
    ["background", TRIGGER_LABEL.background],
    ["user", TRIGGER_LABEL.user],
  ];
  return (
    <div className="flex gap-1" role="group" aria-label="Filter by what started the work">
      {options.map(([key, label]) => (
        <button
          key={key || "all"}
          type="button"
          className="af-btn af-btn-sm"
          aria-pressed={value === key}
          style={value === key ? { background: "var(--bg-soft)", color: "var(--ink)" } : undefined}
          onClick={() => onChange(key)}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

function FocusNote({
  focusFrom,
  focusTo,
  onClear,
}: {
  focusFrom: string;
  focusTo: string;
  onClear: () => void;
}) {
  if (!focusFrom) return null;
  return (
    <div className="mb-3 flex flex-wrap items-center gap-2 text-[12.5px]" style={{ color: "var(--ink-3)" }}>
      <span>
        Narrowed to {formatClock(focusFrom)}
        {focusTo ? ` – ${formatClock(focusTo)}` : ""}
      </span>
      <button type="button" className="af-btn af-btn-sm" onClick={onClear}>
        Show the whole window
      </button>
    </div>
  );
}

function Section({
  title,
  description,
  action,
  testId,
  children,
}: {
  title: string;
  description: string;
  action?: ReactNode;
  testId: string;
  children: ReactNode;
}) {
  return (
    <section className="af-card p-4" data-testid={testId} aria-label={title}>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="m-0 text-[14px] font-semibold" style={{ color: "var(--ink)" }}>
            {title}
          </h2>
          <p className="m-0 mt-1 max-w-[70ch] text-[12px]" style={{ color: "var(--ink-4)" }}>
            {description}
          </p>
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div
      className="rounded-xl px-3.5 py-3"
      style={{ border: "1px solid var(--line)", background: "var(--bg-soft)" }}
    >
      <div className="text-[12px]" style={{ color: "var(--ink-4)" }}>
        {label}
      </div>
      <div className="mt-1 text-[20px] font-semibold tabular-nums" style={{ color: "var(--ink)" }}>
        {value}
      </div>
      {sub && (
        <div className="mt-0.5 text-[11.5px]" style={{ color: "var(--ink-4)" }}>
          {sub}
        </div>
      )}
    </div>
  );
}
