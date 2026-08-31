"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Activity, ChevronDown, CircleAlert, RefreshCw, RotateCcw, X } from "lucide-react";

import { ConfirmationDialog } from "@/components/confirmation-dialog";
import { DateRangePicker } from "@/components/date-range-picker";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { CommunicationConnectionJournal } from "@/features/communication-connections/components/communication-connection-journal";
import {
  communicationJournalKey,
  useCommunicationConnectionActions,
  useCommunicationConnectionDiagnostics,
} from "@/features/communication-connections/hooks/use-communication-connections";
import type {
  CommunicationConnection,
  CommunicationDiagnostics,
  CommunicationJournalWindow,
} from "@/features/communication-connections/schemas";

function healthLabel(value: string): string {
  return value === "no_data" ? "No delivery data" : label(value);
}

function healthColor(value: string): string {
  if (value === "healthy") return "var(--ok)";
  if (value === "degraded") return "var(--warn)";
  return "var(--ink-4)";
}

function formatDuration(value: number | null): string {
  if (value === null) return "—";
  if (value < 1000) return `${Math.round(value)} ms`;
  return `${(value / 1000).toFixed(1)} s`;
}

function formatCompactDuration(value: number | null): string {
  if (value === null) return "—";
  if (value < 1000) return `${Math.round(value)} ms`;
  const seconds = Math.round((value / 1000) * 10) / 10;
  if (seconds >= 60) {
    const totalSeconds = Math.round(seconds);
    return `${Math.floor(totalSeconds / 60)}m ${String(totalSeconds % 60).padStart(2, "0")}s`;
  }
  return `${Number.isInteger(seconds) ? seconds : seconds.toFixed(1)}s`;
}

function formatHealthWindow(window: CommunicationJournalWindow): string {
  if (!window.since || !window.until) return "the selected window";
  const durationMs = new Date(window.until).getTime() - new Date(window.since).getTime();
  const durationHours = durationMs / (60 * 60 * 1000);
  if (Math.abs(durationHours - 24) < 0.01) return "the last 24 hours";
  if (durationHours >= 24 && durationHours % 24 < 0.01) {
    return `the last ${Math.round(durationHours / 24)} days`;
  }
  if (durationHours >= 1 && durationHours % 1 < 0.01) {
    return `the last ${Math.round(durationHours)} hours`;
  }
  return "the selected window";
}

function incidentOutcomeColor(value: string): string {
  if (value === "RECONNECTED") return "var(--ok-muted)";
  if (value === "FAILED") return "var(--err-muted)";
  return "var(--warn-muted)";
}

function formatAgeSeconds(value: number | null): string {
  if (value === null) return "—";
  if (value < 60) return `${Math.round(value)}s`;
  if (value < 3600) return `${Math.round(value / 60)}m`;
  if (value < 86_400) return `${Math.round(value / 3600)}h`;
  return `${Math.round(value / 86_400)}d`;
}

function formatRelativeTimestamp(value: string | null): string {
  if (value === null) return "Never";
  const seconds = Math.max(0, (Date.now() - new Date(value).getTime()) / 1000);
  return `${formatAgeSeconds(seconds)} ago`;
}

function formatTimestamp(value: string): string {
  return new Date(value).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatPercent(value: number | null): string {
  if (value === null) return "—";
  return `${Math.round(value * 100)}%`;
}

function label(value: string): string {
  return value
    .replace(/_/g, " ")
    .toLowerCase()
    .replace(/(^|\s)\S/g, (character) => character.toUpperCase());
}

function terminalDeliveryCount(diagnostics: CommunicationDiagnostics): number {
  return diagnostics.deliveryCounts.succeeded
    + diagnostics.deliveryCounts.deadLettered
    + diagnostics.deliveryCounts.cancelled
    + diagnostics.deliveryCounts.unavailable;
}

function failedDeliveryCount(diagnostics: CommunicationDiagnostics): number {
  return diagnostics.deliveryCounts.deadLettered
    + diagnostics.deliveryCounts.cancelled
    + diagnostics.deliveryCounts.unavailable;
}

function successRateLabel(diagnostics: CommunicationDiagnostics): string {
  const terminal = terminalDeliveryCount(diagnostics);
  if (diagnostics.deliverySuccessRate === null) return "No completed deliveries";
  return `${formatPercent(diagnostics.deliverySuccessRate)} (${diagnostics.deliveryCounts.succeeded}/${terminal})`;
}

const PIPELINE_STAGES = [
  { key: "providerObserved", label: "Provider observed" },
  { key: "policyAdmitted", label: "Policy admitted" },
  { key: "queued", label: "Queued" },
  { key: "agentClaimed", label: "Agent claimed" },
  { key: "modelCompleted", label: "Model completed" },
  { key: "replyQueued", label: "Reply queued" },
  { key: "providerDelivered", label: "Provider delivered" },
] as const;

function PipelineSummary({ pipeline, timeRange }: { pipeline: CommunicationDiagnostics["pipeline"]; timeRange: CommunicationJournalWindow }) {
  const observed = pipeline.providerObserved;
  return (
    <section
      aria-labelledby="pipeline-summary-heading"
      className="rounded-lg p-3"
      style={{ border: "1px solid var(--line)", background: "var(--bg-elev)" }}
      data-pipeline-summary
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 id="pipeline-summary-heading" className="m-0 text-sm font-semibold" style={{ color: "var(--ink-2)" }}>Pipeline</h2>
          <p className="mb-0 mt-1 text-xs" style={{ color: "var(--ink-4)" }}>
            Message flow through the delivery pipeline over {formatHealthWindow(timeRange)}. Counts that fall behind earlier stages show where traffic drops off.
          </p>
        </div>
        {pipeline.deadLettered > 0 && (
          <div className="text-xs font-medium" style={{ color: "var(--err)" }}>
            {pipeline.deadLettered} dead-lettered
          </div>
        )}
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-4 lg:grid-cols-7">
        {PIPELINE_STAGES.map((stage) => {
          const count = pipeline[stage.key];
          const share = observed > 0 ? count / observed : null;
          return (
            <div key={stage.key} className="rounded-md px-2.5 py-2" style={{ background: "var(--bg-soft)" }} data-pipeline-stage={stage.key}>
              <div className="text-[11px]" style={{ color: "var(--ink-4)" }}>{stage.label}</div>
              <div className="mt-0.5 text-sm font-semibold" style={{ color: "var(--ink)" }}>{count.toLocaleString()}</div>
              <div className="mt-0.5 text-[11px]" style={{ color: share !== null && share < 1 ? "var(--warn)" : "var(--ink-4)" }}>
                {formatPercent(share)}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function LatestTransitions({ transitions }: { transitions: CommunicationDiagnostics["latestTransitions"] }) {
  return (
    <section aria-labelledby="latest-transitions-heading" data-latest-transitions>
      <div className="mb-2">
        <h2 id="latest-transitions-heading" className="m-0 text-sm font-semibold" style={{ color: "var(--ink-2)" }}>Latest transitions</h2>
        <p className="mb-0 mt-1 text-xs" style={{ color: "var(--ink-4)" }}>
          The latest {transitions.length} delivery and connection transitions, newest first.
        </p>
      </div>
      {transitions.length === 0 ? (
        <p className="m-0 rounded-lg p-3 text-xs" style={{ border: "1px solid var(--line)", background: "var(--bg-elev)", color: "var(--ink-4)" }}>
          No transitions in this window
        </p>
      ) : (
        <div className="af-card overflow-x-auto" style={{ padding: 0 }}>
          <table className="w-full min-w-[560px] border-collapse text-xs">
            <thead>
              <tr className="border-b text-left" style={{ borderColor: "var(--line)", color: "var(--ink-4)" }}>
                <th className="px-3 py-2 font-medium">Occurred</th>
                <th className="px-3 py-2 font-medium">Stage</th>
                <th className="px-3 py-2 font-medium">Delivery</th>
                <th className="px-3 py-2 font-medium">Admission</th>
                <th className="px-3 py-2 font-medium">Attempt</th>
                <th className="px-3 py-2 font-medium">Elapsed</th>
              </tr>
            </thead>
            <tbody>
              {transitions.map((transition, index) => (
                <tr
                  key={`${transition.occurredAt}-${transition.stage}-${index}`}
                  data-latest-transition={transition.stage}
                  className="border-b last:border-b-0"
                  style={{ borderColor: "var(--line)" }}
                >
                  <td className="whitespace-nowrap px-3 py-2" style={{ color: "var(--ink-3)" }}>{formatTimestamp(transition.occurredAt)}</td>
                  <td className="whitespace-nowrap px-3 py-2 capitalize" style={{ color: "var(--ink)" }}>{label(transition.stage)}</td>
                  <td className="px-3 py-2" style={{ color: "var(--ink-3)" }}>
                    {transition.deliveryId ? <span className="font-mono text-[11px]">{transition.deliveryId.slice(0, 8)}…</span> : "Connection"}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 capitalize" style={{ color: "var(--ink-3)" }}>{transition.disposition ? label(transition.disposition) : "—"}</td>
                  <td className="whitespace-nowrap px-3 py-2" style={{ color: "var(--ink-3)" }}>{transition.attemptNumber}</td>
                  <td className="whitespace-nowrap px-3 py-2" style={{ color: "var(--ink-3)" }}>{formatDuration(transition.durationMs)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

type FailureGroup = {
  key: string;
  stage: string;
  errorCode: string | null;
  errorSummary: string | null;
  errorDetails: CommunicationDiagnostics["recentFailures"][number]["errorDetails"];
  count: number;
  firstOccurredAt: string;
  lastOccurredAt: string;
  deliveryIds: string[];
};

function groupFailures(failures: CommunicationDiagnostics["recentFailures"]): FailureGroup[] {
  const groups = new Map<string, FailureGroup>();
  for (const failure of failures) {
    const details = failure.errorDetails;
    // Request IDs and retry-after values identify one provider response, not
    // the underlying failure. Keep them in each occurrence, but do not let
    // them split otherwise identical incidents into separate cards.
    const key = JSON.stringify({
      code: failure.errorCode ?? failure.stage,
      summary: failure.errorSummary,
      category: details?.category ?? null,
      operation: details?.operation ?? null,
      httpStatus: details?.httpStatus ?? null,
      providerCode: details?.providerCode ?? null,
      retryable: details?.retryable ?? null,
    });
    const existing = groups.get(key);
    if (existing) {
      existing.count += 1;
      if (failure.deliveryId && !existing.deliveryIds.includes(failure.deliveryId)) {
        existing.deliveryIds.push(failure.deliveryId);
      }
      if (failure.occurredAt < existing.firstOccurredAt) existing.firstOccurredAt = failure.occurredAt;
      if (failure.occurredAt > existing.lastOccurredAt) existing.lastOccurredAt = failure.occurredAt;
      continue;
    }
    groups.set(key, {
      key,
      stage: failure.stage,
      errorCode: failure.errorCode,
      errorSummary: failure.errorSummary,
      errorDetails: failure.errorDetails,
      count: 1,
      firstOccurredAt: failure.occurredAt,
      lastOccurredAt: failure.occurredAt,
      deliveryIds: failure.deliveryId ? [failure.deliveryId] : [],
    });
  }
  return Array.from(groups.values()).sort((left, right) => right.lastOccurredAt.localeCompare(left.lastOccurredAt));
}

function errorMessage(error: unknown): string | null {
  return error instanceof Error ? error.message : error ? "The recovery request failed." : null;
}

export function CommunicationConnectionDiagnostics({
  agentId,
  connection,
  canEdit,
  alwaysExpanded = false,
}: {
  agentId: string;
  connection: CommunicationConnection;
  canEdit: boolean;
  alwaysExpanded?: boolean;
}) {
  const [open, setOpen] = useState(alwaysExpanded);
  const [reconnectOpen, setReconnectOpen] = useState(false);
  const [retryDeliveryId, setRetryDeliveryId] = useState<string | null>(null);
  const [windowRange, setWindowRange] = useState<CommunicationJournalWindow | null>(null);
  const [expandedFailureKey, setExpandedFailureKey] = useState<string | null>(null);
  const diagnostics = useCommunicationConnectionDiagnostics(agentId, connection.id, open, windowRange ?? {});
  const { reconnectConnection, retryDelivery } = useCommunicationConnectionActions();
  const queryClient = useQueryClient();
  const actionError = errorMessage(reconnectConnection.error) ?? errorMessage(retryDelivery.error);
  const effectiveWindow: CommunicationJournalWindow = windowRange ?? (diagnostics.data
    ? { since: diagnostics.data.windowStart, until: diagnostics.data.windowEnd }
    : {});
  const lastCheckedAt = diagnostics.dataUpdatedAt
    ? new Date(diagnostics.dataUpdatedAt).toISOString()
    : null;
  const failureGroups = diagnostics.data ? groupFailures(diagnostics.data.recentFailures) : [];

  function handleWindowChange(from: string, to: string) {
    setWindowRange(from || to ? { since: from || undefined, until: to || undefined } : null);
  }

  function refreshDiagnostics() {
    void diagnostics.refetch();
    void queryClient.invalidateQueries({ queryKey: communicationJournalKey.all });
  }

  return (
    <>
      <div className="mt-4 border-t pt-3" style={{ borderColor: "var(--line)" }}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.1em]" style={{ color: "var(--ink-4)" }}>
              Communication health
            </div>
            <p className="mb-0 mt-1 text-xs" style={{ color: "var(--ink-3)" }}>
              Provider connectivity and end-to-end delivery are measured separately.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {open && diagnostics.data && (
              <button
                type="button"
                className="af-btn af-btn-sm"
                disabled={diagnostics.isFetching}
                onClick={refreshDiagnostics}
              >
                <RefreshCw size={14} className={diagnostics.isFetching ? "animate-spin" : undefined} />
                Refresh
              </button>
            )}
            {canEdit && (
              <button
                type="button"
                className="af-btn af-btn-sm"
                disabled={reconnectConnection.isPending}
                onClick={() => setReconnectOpen(true)}
              >
                <RefreshCw size={14} />
                {reconnectConnection.isPending ? "Reconnecting…" : "Reconnect"}
              </button>
            )}
            {!alwaysExpanded && (
              <button
                type="button"
                className="af-btn af-btn-sm"
                aria-expanded={open}
                onClick={() => setOpen((current) => !current)}
              >
                {open ? <X size={14} /> : <Activity size={14} />}
                {open ? "Hide diagnostics" : "Diagnostics"}
              </button>
            )}
          </div>
        </div>

        {open && (
          <div className="mt-3 flex flex-col gap-3">
            {diagnostics.isPending && <p className="m-0 text-xs" style={{ color: "var(--ink-3)" }}>Loading diagnostics…</p>}
            {diagnostics.error && (
              <div className="flex items-center gap-2 text-xs" style={{ color: "var(--err)" }} role="alert">
                <CircleAlert size={14} /> Could not load connection diagnostics.
              </div>
            )}
            {diagnostics.data && (
              <>
                <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg p-3" style={{ border: "1px solid var(--line)", background: "var(--bg-elev)" }}>
                  <div>
                    <div className="text-xs font-semibold" style={{ color: "var(--ink-2)" }}>Diagnostics window</div>
                    <p className="mb-0 mt-1 text-xs" style={{ color: "var(--ink-4)" }}>
                      Windowed metrics and activity use this range. Current connection state is shown separately.
                    </p>
                  </div>
                  <DateRangePicker
                    from={effectiveWindow.since ?? ""}
                    to={effectiveWindow.until ?? ""}
                    onChange={handleWindowChange}
                    placeholder="Time range"
                    width="14rem"
                    ariaLabel="Select diagnostics time range"
                  />
                </div>

                <div className="grid gap-2 sm:grid-cols-2">
                  <HealthCard
                    label="Provider connectivity"
                    value={diagnostics.data.providerConnectivity ? label(diagnostics.data.providerConnectivity) : "Not observed"}
                    detail={`Observed ${formatRelativeTimestamp(diagnostics.data.connection.lastHealthAt)}`}
                    color={providerColor(diagnostics.data.providerConnectivity)}
                  />
                  <HealthCard
                    label="End-to-end delivery"
                    value={healthLabel(diagnostics.data.endToEndHealth)}
                    detail="Based on current provider state and delivery outcomes"
                    color={healthColor(diagnostics.data.endToEndHealth)}
                  />
                </div>

                <PipelineSummary pipeline={diagnostics.data.pipeline} timeRange={effectiveWindow} />

                <div className="rounded-lg p-3" style={{ border: "1px solid var(--line)", background: "var(--bg-elev)" }}>
                  <div className="text-xs font-semibold" style={{ color: "var(--ink-2)" }}>Health signals</div>
                  <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-5">
                    <StatTile label="Last successful connection" value={formatRelativeTimestamp(diagnostics.data.lastSuccessfulConnectionAt)} />
                    <StatTile
                      label="Current connection error"
                      value={formatAgeSeconds(diagnostics.data.currentErrorAgeSeconds)}
                      warn={diagnostics.data.currentErrorAgeSeconds !== null}
                    />
                    <StatTile
                      label="Consecutive delivery failures"
                      value={String(diagnostics.data.consecutiveFailureCount)}
                      warn={diagnostics.data.consecutiveFailureCount > 0}
                    />
                    <StatTile label="Delivery success rate" value={successRateLabel(diagnostics.data)} />
                    <StatTile label="Oldest pending delivery" value={formatAgeSeconds(diagnostics.data.oldestPendingDeliveryAgeSeconds)} />
                  </div>
                </div>

                <ConnectionHealth
                  states={diagnostics.data.connectionHistory}
                  incidents={diagnostics.data.connectionIncidents}
                  reconnectCount={diagnostics.data.reconnectCount}
                  medianConnectTimeMs={diagnostics.data.medianConnectTimeMs}
                  longestOutageMs={diagnostics.data.longestOutageMs}
                  timeRange={effectiveWindow}
                />

                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="rounded-lg p-3" style={{ border: "1px solid var(--line)", background: "var(--bg-elev)" }}>
                    <div className="text-xs font-semibold" style={{ color: "var(--ink-2)" }}>Delivery counts</div>
                    <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs" style={{ color: "var(--ink-3)" }}>
                      <span>Total</span><strong style={{ color: "var(--ink)" }}>{diagnostics.data.deliveryCounts.total}</strong>
                      <span>Successful</span><strong style={{ color: "var(--ink)" }}>{diagnostics.data.deliveryCounts.succeeded}</strong>
                      <span>In progress</span><strong style={{ color: "var(--ink)" }}>{diagnostics.data.deliveryCounts.pending + diagnostics.data.deliveryCounts.processing}</strong>
                      <span>Failed / unavailable</span><strong style={{ color: failedDeliveryCount(diagnostics.data) ? "var(--err)" : "var(--ink)" }}>{failedDeliveryCount(diagnostics.data)}</strong>
                    </div>
                  </div>
                  <div className="rounded-lg p-3" style={{ border: "1px solid var(--line)", background: "var(--bg-elev)" }}>
                    <div className="text-xs font-semibold" style={{ color: "var(--ink-2)" }}>Processing time</div>
                    <div className="mt-1 text-[11px]" style={{ color: "var(--ink-4)" }}>Claim to completion for terminal deliveries</div>
                    <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs" style={{ color: "var(--ink-3)" }}>
                      <span>Samples</span><strong style={{ color: "var(--ink)" }}>{diagnostics.data.latency.sampleCount}</strong>
                      <span>Average / p50</span><strong style={{ color: "var(--ink)" }}>{formatDuration(diagnostics.data.latency.averageMs)} / {formatDuration(diagnostics.data.latency.p50Ms)}</strong>
                      <span>Latest</span><strong style={{ color: "var(--ink)" }}>{formatDuration(diagnostics.data.latency.latestMs)}</strong>
                    </div>
                  </div>
                </div>

                <DiagnosticsList title="Recent failures">
                  {failureGroups.length === 0 ? (
                    <p className="m-0 text-xs" style={{ color: "var(--ink-4)" }}>No recent failures in this window</p>
                  ) : failureGroups.map((failure) => {
                    const expanded = expandedFailureKey === failure.key;
                    return (
                      <Collapsible
                        key={failure.key}
                        open={expanded}
                        onOpenChange={(nextOpen) => setExpandedFailureKey(nextOpen ? failure.key : null)}
                      >
                        <div data-failure-card={failure.key} className="rounded-md" style={{ border: "1px solid var(--line)" }}>
                          <div className="flex items-start justify-between gap-3 p-2.5">
                            <div className="min-w-0 text-xs">
                              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                                <span className="font-medium" style={{ color: "var(--err)" }}>{failure.errorCode ?? label(failure.stage)}</span>
                                {failure.count > 1 && <span style={{ color: "var(--ink-3)" }}>×{failure.count}</span>}
                              </div>
                              {failure.errorSummary && <div className="mt-1" style={{ color: "var(--ink-3)" }}>{failure.errorSummary}</div>}
                              <div className="mt-1 text-[11px]" style={{ color: "var(--ink-4)" }}>
                                {failure.count > 1 ? `${failure.count} occurrences · ` : ""}{formatTimestamp(failure.lastOccurredAt)}
                              </div>
                            </div>
                            <CollapsibleTrigger asChild>
                              <button type="button" className="inline-flex shrink-0 items-center gap-1 text-xs underline" style={{ color: "var(--ink-3)" }}>
                                {expanded ? "Hide details" : "Show details"}
                                <ChevronDown size={14} className={expanded ? "rotate-180" : undefined} />
                              </button>
                            </CollapsibleTrigger>
                          </div>
                          <CollapsibleContent className="border-t px-2.5 py-2.5" style={{ borderColor: "var(--line)" }}>
                            <div className="grid gap-2 text-xs sm:grid-cols-2">
                              <FailureDetail label="Stage" value={label(failure.stage)} />
                              <FailureDetail label="Error code" value={failure.errorCode ?? "—"} />
                              <FailureDetail label="First seen" value={formatTimestamp(failure.firstOccurredAt)} />
                              <FailureDetail label="Last seen" value={formatTimestamp(failure.lastOccurredAt)} />
                              <FailureDetail label="Delivery IDs" value={failure.deliveryIds.length > 0 ? failure.deliveryIds.join(", ") : "Connection-level"} />
                            </div>
                            <div className="mt-3">
                              <div className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: "var(--ink-4)" }}>Error details</div>
                              <p className="mb-0 mt-1 text-xs" style={{ color: "var(--ink-3)" }}>{failure.errorSummary ?? "No safe detail was recorded."}</p>
                            </div>
                            {failure.errorDetails && (
                              <div className="mt-3 grid gap-2 text-xs sm:grid-cols-2">
                                <FailureDetail label="Category" value={label(failure.errorDetails.category)} />
                                <FailureDetail label="Operation" value={label(failure.errorDetails.operation)} />
                                {failure.errorDetails.httpStatus !== null && (
                                  <FailureDetail label="HTTP status" value={String(failure.errorDetails.httpStatus)} />
                                )}
                                <FailureDetail label="Provider code" value={failure.errorDetails.providerCode ?? "—"} />
                                <FailureDetail label="Retryable" value={failure.errorDetails.retryable ? "Yes" : "No"} />
                                {failure.errorDetails.retryAfterSeconds !== null && (
                                  <FailureDetail label="Retry after" value={`${failure.errorDetails.retryAfterSeconds}s`} />
                                )}
                                {failure.errorDetails.requestId && (
                                  <FailureDetail label="Request ID" value={failure.errorDetails.requestId} />
                                )}
                              </div>
                            )}
                          </CollapsibleContent>
                        </div>
                      </Collapsible>
                    );
                  })}
                </DiagnosticsList>

                <LatestTransitions transitions={diagnostics.data.latestTransitions} />

                <section aria-labelledby="delivery-transitions-heading">
                  <div className="mb-2">
                    <h2 id="delivery-transitions-heading" className="m-0 text-sm font-semibold" style={{ color: "var(--ink-2)" }}>Delivery transitions</h2>
                    <p className="mb-0 mt-1 text-xs" style={{ color: "var(--ink-4)" }}>The full lifecycle of each inbound and outbound Delivery.</p>
                  </div>
                  <CommunicationConnectionJournal
                    agentId={agentId}
                    connectionId={connection.id}
                    kind="delivery"
                    canEdit={canEdit}
                    timeRange={effectiveWindow}
                    lastCheckedAt={lastCheckedAt}
                    onRetryDelivery={setRetryDeliveryId}
                  />
                </section>

              </>
            )}
          </div>
        )}
        {actionError && <p className="mt-2 mb-0 text-xs" style={{ color: "var(--err)" }} role="alert">{actionError}</p>}
      </div>

      <ConfirmationDialog
        open={reconnectOpen}
        onOpenChange={setReconnectOpen}
        title="Reconnect this connection?"
        description="The provider session will be restarted. Existing deliveries remain queued and are not duplicated."
        confirmLabel="Reconnect"
        pendingLabel="Reconnecting…"
        icon={<RefreshCw size={18} />}
        isPending={reconnectConnection.isPending}
        onConfirm={async () => {
          await reconnectConnection.mutateAsync({ agentId, connectionId: connection.id });
          setReconnectOpen(false);
        }}
      />

      <ConfirmationDialog
        open={Boolean(retryDeliveryId)}
        onOpenChange={(nextOpen) => { if (!nextOpen) setRetryDeliveryId(null); }}
        title="Retry this delivery?"
        description="The existing delivery and idempotency key will be reused, so this action will not create a duplicate conversation message."
        confirmLabel="Retry delivery"
        pendingLabel="Retrying…"
        icon={<RotateCcw size={18} />}
        isPending={retryDelivery.isPending}
        onConfirm={async () => {
          if (!retryDeliveryId) return;
          await retryDelivery.mutateAsync({ agentId, connectionId: connection.id, deliveryId: retryDeliveryId });
          setRetryDeliveryId(null);
        }}
      />
    </>
  );
}

function DiagnosticsList({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg p-3" style={{ border: "1px solid var(--line)", background: "var(--bg-elev)" }}>
      <div className="mb-2 flex items-center justify-between gap-3 text-xs font-semibold" style={{ color: "var(--ink-2)" }}>
        <span>{title}</span>
      </div>
      <div className="space-y-2">{children}</div>
    </div>
  );
}

function FailureDetail({ label: detailLabel, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-md px-2 py-1.5" style={{ background: "var(--bg-soft)" }}>
      <div className="text-[11px]" style={{ color: "var(--ink-4)" }}>{detailLabel}</div>
      <div className="mt-0.5 break-all text-xs" style={{ color: "var(--ink-2)" }}>{value}</div>
    </div>
  );
}

function ConnectionHealth({
  states,
  incidents,
  reconnectCount,
  medianConnectTimeMs,
  longestOutageMs,
  timeRange,
}: {
  states: CommunicationDiagnostics["connectionHistory"];
  incidents: CommunicationDiagnostics["connectionIncidents"];
  reconnectCount: number;
  medianConnectTimeMs: number | null;
  longestOutageMs: number | null;
  timeRange: CommunicationJournalWindow;
}) {
  const chronologicalStates = [...states].reverse();

  return (
    <section aria-labelledby="connection-health-heading" className="rounded-lg p-3" style={{ border: "1px solid var(--line)", background: "var(--bg-elev)" }}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 id="connection-health-heading" className="m-0 text-sm font-semibold" style={{ color: "var(--ink-2)" }}>Connection health</h2>
          <div className="mt-1 text-xs" style={{ color: "var(--ink-4)" }}>Health over {formatHealthWindow(timeRange)}</div>
        </div>
      </div>
      {states.length === 0 ? (
        <p className="mb-0 mt-3 text-xs" style={{ color: "var(--ink-4)" }}>No connection state history in this window</p>
      ) : (
        <>
          <div className="mt-4 flex h-2 w-full gap-px overflow-hidden rounded-full" aria-label="Connection health timeline">
            {chronologicalStates.map((state, index) => (
              <div
                key={`${state.startedAt}-${state.status}-${index}`}
                role="img"
                aria-label={`${label(state.status)} for ${formatCompactDuration(state.durationMs)} starting ${formatTimestamp(state.startedAt)}`}
                title={`${label(state.status)} · ${formatCompactDuration(state.durationMs)} · ${formatTimestamp(state.startedAt)}`}
                className="min-w-[3px]"
                style={{ flex: `${Math.max(state.durationMs, 1)} 1 0%`, background: providerColor(state.status) }}
              />
            ))}
          </div>
          <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px]" style={{ color: "var(--ink-4)" }}>
            {Array.from(new Set(chronologicalStates.map((state) => state.status))).map((status) => (
              <span key={status} className="inline-flex items-center gap-1">
                <span className="h-2 w-2 rounded-sm" style={{ background: providerColor(status) }} />
                {label(status)}
              </span>
            ))}
          </div>
        </>
      )}
      <div className="mt-3 text-xs" style={{ color: "var(--ink-2)" }}>
        {reconnectCount} reconnect{reconnectCount === 1 ? "" : "s"} · Median connect time {formatCompactDuration(medianConnectTimeMs)} · Longest outage {formatCompactDuration(longestOutageMs)}
      </div>

      <div className="mt-4">
        <div className="mb-2 text-xs font-semibold" style={{ color: "var(--ink-2)" }}>Recent incidents</div>
        {incidents.length === 0 ? (
          <p className="m-0 text-xs" style={{ color: "var(--ink-4)" }}>No connection attempts in this window</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[620px] border-collapse text-xs">
              <thead>
                <tr className="border-b text-left" style={{ borderColor: "var(--line)", color: "var(--ink-4)" }}>
                  <th className="px-1 py-2 font-medium">Started</th>
                  <th className="px-1 py-2 font-medium">Outcome</th>
                  <th className="px-1 py-2 font-medium">Connect time</th>
                  <th className="px-1 py-2 font-medium">Outage</th>
                  <th className="px-1 py-2 font-medium">Cause</th>
                </tr>
              </thead>
              <tbody>
                {incidents.map((incident, index) => (
                  <tr key={`${incident.startedAt}-${incident.outcome}-${index}`} className="border-b last:border-b-0" style={{ borderColor: "var(--line)" }}>
                    <td className="whitespace-nowrap px-1 py-2" style={{ color: "var(--ink-3)" }}>{formatTimestamp(incident.startedAt)}</td>
                    <td className="whitespace-nowrap px-1 py-2 font-medium" style={{ color: incidentOutcomeColor(incident.outcome) }}>{label(incident.outcome)}</td>
                    <td className="whitespace-nowrap px-1 py-2" style={{ color: "var(--ink-3)" }}>{formatCompactDuration(incident.connectTimeMs)}</td>
                    <td className="whitespace-nowrap px-1 py-2" style={{ color: "var(--ink-3)" }}>{formatCompactDuration(incident.outageMs)}</td>
                    <td className="max-w-[220px] px-1 py-2" style={{ color: "var(--ink-3)" }}>
                      <div>{incident.causeCode ? label(incident.causeCode) : "—"}</div>
                      {incident.causeSummary && <div className="mt-0.5 truncate text-[11px]" style={{ color: "var(--ink-4)" }} title={incident.causeSummary}>{incident.causeSummary}</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}

function StatTile({ label, value, warn = false }: { label: string; value: string; warn?: boolean }) {
  return (
    <div className="rounded-md px-2.5 py-2" style={{ background: "var(--bg-soft)" }}>
      <div className="text-[11px]" style={{ color: "var(--ink-4)" }}>{label}</div>
      <div className="mt-0.5 text-sm font-semibold" style={{ color: warn ? "var(--err)" : "var(--ink)" }}>{value}</div>
    </div>
  );
}

function HealthCard({ label, value, detail, color }: { label: string; value: string; detail: string; color: string }) {
  return (
    <div className="rounded-lg p-3" style={{ border: "1px solid var(--line)", background: "var(--bg-elev)" }}>
      <div className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: "var(--ink-4)" }}>{label}</div>
      <div className="mt-1 flex items-center gap-2 text-sm font-medium" style={{ color: "var(--ink)" }}>
        <span className="h-2 w-2 rounded-full" style={{ background: color }} />{value}
      </div>
      <div className="mt-1 text-[11px]" style={{ color: "var(--ink-4)" }}>{detail}</div>
    </div>
  );
}

function providerColor(value: string | null): string {
  if (value === "CONNECTED") return "var(--ok-muted)";
  if (value === "DEGRADED" || value === "CONNECTING") return "var(--warn-muted)";
  if (value === "ERROR") return "var(--err-muted)";
  return "var(--ink-4)";
}
