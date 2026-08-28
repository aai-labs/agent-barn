"use client";

import { useState } from "react";
import { Activity, CircleAlert, RefreshCw, RotateCcw, X } from "lucide-react";

import { ConfirmationDialog } from "@/components/confirmation-dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { CommunicationConnectionJournal } from "@/features/communication-connections/components/communication-connection-journal";
import {
  useCommunicationConnectionActions,
  useCommunicationConnectionDiagnostics,
} from "@/features/communication-connections/hooks/use-communication-connections";
import type {
  CommunicationConnection,
  CommunicationDiagnostics,
  CommunicationJournalKind,
} from "@/features/communication-connections/schemas";

const PIPELINE_STEPS: Array<[keyof CommunicationDiagnostics["pipeline"], string]> = [
  ["providerObserved", "Observed"],
  ["policyAdmitted", "Admitted"],
  ["queued", "Queued"],
  ["agentClaimed", "Claimed"],
  ["modelCompleted", "Model complete"],
  ["replyQueued", "Reply queued"],
  ["providerDelivered", "Delivered"],
];

function healthLabel(value: string): string {
  return value === "no_data" ? "No delivery data" : value.replace(/_/g, " ");
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

function formatPercent(value: number | null): string {
  if (value === null) return "—";
  return `${Math.round(value * 100)}%`;
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
  const [activityKind, setActivityKind] = useState<CommunicationJournalKind>("delivery");
  const diagnostics = useCommunicationConnectionDiagnostics(agentId, connection.id, open);
  const { reconnectConnection, retryDelivery } = useCommunicationConnectionActions();
  const actionError = errorMessage(reconnectConnection.error) ?? errorMessage(retryDelivery.error);

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
                onClick={() => void diagnostics.refetch()}
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
                <div className="grid gap-2 sm:grid-cols-2">
                  <HealthCard
                    label="Provider connectivity"
                    value={diagnostics.data.providerConnectivity ?? "Not observed"}
                    color={providerColor(diagnostics.data.providerConnectivity)}
                  />
                  <HealthCard
                    label="End-to-end delivery"
                    value={healthLabel(diagnostics.data.endToEndHealth)}
                    color={healthColor(diagnostics.data.endToEndHealth)}
                  />
                </div>

                <div className="rounded-lg p-3" style={{ border: "1px solid var(--line)", background: "var(--bg-elev)" }}>
                  <div className="text-xs font-semibold" style={{ color: "var(--ink-2)" }}>Health signals</div>
                  <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-5">
                    <StatTile label="Last successful connection" value={formatRelativeTimestamp(diagnostics.data.lastSuccessfulConnectionAt)} />
                    <StatTile
                      label="Current error age"
                      value={formatAgeSeconds(diagnostics.data.currentErrorAgeSeconds)}
                      warn={diagnostics.data.currentErrorAgeSeconds !== null}
                    />
                    <StatTile
                      label="Consecutive failures"
                      value={String(diagnostics.data.consecutiveFailureCount)}
                      warn={diagnostics.data.consecutiveFailureCount > 0}
                    />
                    <StatTile label="Delivery success rate" value={formatPercent(diagnostics.data.deliverySuccessRate)} />
                    <StatTile label="Oldest pending delivery" value={formatAgeSeconds(diagnostics.data.oldestPendingDeliveryAgeSeconds)} />
                  </div>
                </div>

                <div className="rounded-lg p-3" style={{ border: "1px solid var(--line)", background: "var(--bg-elev)" }}>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="text-xs font-semibold" style={{ color: "var(--ink-2)" }}>Pipeline, last window</div>
                    <div className="text-xs" style={{ color: "var(--ink-4)" }}>
                      Queue {diagnostics.data.queueDepth}
                      {diagnostics.data.oldestQueuedAgeSeconds !== null && ` · oldest ${Math.round(diagnostics.data.oldestQueuedAgeSeconds)}s`}
                    </div>
                  </div>
                  <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
                    {PIPELINE_STEPS.map(([key, label]) => (
                      <div key={key} className="rounded-md px-2.5 py-2" style={{ background: "var(--bg-soft)" }}>
                        <div className="text-[11px]" style={{ color: "var(--ink-4)" }}>{label}</div>
                        <div className="mt-0.5 text-sm font-semibold" style={{ color: "var(--ink)" }}>{diagnostics.data.pipeline[key]}</div>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="rounded-lg p-3" style={{ border: "1px solid var(--line)", background: "var(--bg-elev)" }}>
                    <div className="text-xs font-semibold" style={{ color: "var(--ink-2)" }}>Delivery counts</div>
                    <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs" style={{ color: "var(--ink-3)" }}>
                      <span>Successful</span><strong style={{ color: "var(--ink)" }}>{diagnostics.data.deliveryCounts.succeeded}</strong>
                      <span>Pending / processing</span><strong style={{ color: "var(--ink)" }}>{diagnostics.data.deliveryCounts.pending + diagnostics.data.deliveryCounts.processing}</strong>
                      <span>Dead-lettered</span><strong style={{ color: diagnostics.data.deliveryCounts.deadLettered ? "var(--err)" : "var(--ink)" }}>{diagnostics.data.deliveryCounts.deadLettered}</strong>
                    </div>
                  </div>
                  <div className="rounded-lg p-3" style={{ border: "1px solid var(--line)", background: "var(--bg-elev)" }}>
                    <div className="text-xs font-semibold" style={{ color: "var(--ink-2)" }}>Delivery latency</div>
                    <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs" style={{ color: "var(--ink-3)" }}>
                      <span>Samples</span><strong style={{ color: "var(--ink)" }}>{diagnostics.data.latency.sampleCount}</strong>
                      <span>Average / p50</span><strong style={{ color: "var(--ink)" }}>{formatDuration(diagnostics.data.latency.averageMs)} / {formatDuration(diagnostics.data.latency.p50Ms)}</strong>
                      <span>Latest</span><strong style={{ color: "var(--ink)" }}>{formatDuration(diagnostics.data.latency.latestMs)}</strong>
                    </div>
                  </div>
                </div>

                <Tabs value={activityKind} onValueChange={(value) => setActivityKind(value as CommunicationJournalKind)} className="gap-4">
                  <TabsList
                    variant="line"
                    aria-label="Connection activity view"
                    className="h-auto w-full justify-start gap-1 border-b p-0 group-data-horizontal/tabs:h-auto"
                    style={{ borderColor: "var(--line)" }}
                  >
                    <TabsTrigger
                      value="delivery"
                      className="h-auto flex-none rounded-none border-0 bg-transparent px-4 py-3 text-sm font-medium text-[var(--ink-3)] shadow-none hover:text-[var(--ink)] group-data-horizontal/tabs:after:inset-x-4 group-data-horizontal/tabs:after:bottom-[-1px] after:rounded-[2px_2px_0_0] after:bg-[var(--ink)] data-active:bg-transparent data-active:font-semibold data-active:text-[var(--ink)] data-active:shadow-none"
                    >
                      Delivery transitions
                    </TabsTrigger>
                    <TabsTrigger
                      value="connection"
                      className="h-auto flex-none rounded-none border-0 bg-transparent px-4 py-3 text-sm font-medium text-[var(--ink-3)] shadow-none hover:text-[var(--ink)] group-data-horizontal/tabs:after:inset-x-4 group-data-horizontal/tabs:after:bottom-[-1px] after:rounded-[2px_2px_0_0] after:bg-[var(--ink)] data-active:bg-transparent data-active:font-semibold data-active:text-[var(--ink)] data-active:shadow-none"
                    >
                      Connection events
                    </TabsTrigger>
                  </TabsList>
                  {/* forceMount + CSS-hide (rather than Radix's default unmount-on-switch) so each
                      tab keeps its own filters, expanded row, and query cache when you switch away
                      and back — a remount was silently resetting filters and re-fetching. */}
                  <TabsContent value="delivery" forceMount className="data-[state=inactive]:hidden">
                    <CommunicationConnectionJournal
                      agentId={agentId}
                      connectionId={connection.id}
                      kind="delivery"
                      canEdit={canEdit}
                      lastCheckedAt={diagnostics.data.windowEnd}
                      onRetryDelivery={setRetryDeliveryId}
                    />
                  </TabsContent>
                  <TabsContent value="connection" forceMount className="data-[state=inactive]:hidden">
                    <CommunicationConnectionJournal
                      agentId={agentId}
                      connectionId={connection.id}
                      kind="connection"
                      canEdit={canEdit}
                      lastCheckedAt={diagnostics.data.windowEnd}
                      onRetryDelivery={setRetryDeliveryId}
                    />
                  </TabsContent>
                </Tabs>
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

function StatTile({ label, value, warn = false }: { label: string; value: string; warn?: boolean }) {
  return (
    <div className="rounded-md px-2.5 py-2" style={{ background: "var(--bg-soft)" }}>
      <div className="text-[11px]" style={{ color: "var(--ink-4)" }}>{label}</div>
      <div className="mt-0.5 text-sm font-semibold" style={{ color: warn ? "var(--err)" : "var(--ink)" }}>{value}</div>
    </div>
  );
}

function HealthCard({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="rounded-lg p-3" style={{ border: "1px solid var(--line)", background: "var(--bg-elev)" }}>
      <div className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: "var(--ink-4)" }}>{label}</div>
      <div className="mt-1 flex items-center gap-2 text-sm font-medium capitalize" style={{ color: "var(--ink)" }}>
        <span className="h-2 w-2 rounded-full" style={{ background: color }} />{value}
      </div>
    </div>
  );
}

function providerColor(value: string | null): string {
  if (value === "CONNECTED") return "var(--ok)";
  if (value === "DEGRADED" || value === "CONNECTING") return "var(--warn)";
  if (value === "ERROR") return "var(--err)";
  return "var(--ink-4)";
}
