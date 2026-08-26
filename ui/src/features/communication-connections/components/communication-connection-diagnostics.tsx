"use client";

import { useState } from "react";
import { CircleAlert, RefreshCw, RotateCcw, X } from "lucide-react";

import { ConfirmationDialog } from "@/components/confirmation-dialog";
import {
  useCommunicationConnectionActions,
  useCommunicationConnectionDiagnostics,
} from "@/features/communication-connections/hooks/use-communication-connections";
import type {
  CommunicationConnection,
  CommunicationDiagnostics,
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

function formatTimestamp(value: string): string {
  return new Date(value).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function formatDuration(value: number | null): string {
  if (value === null) return "—";
  if (value < 1000) return `${Math.round(value)} ms`;
  return `${(value / 1000).toFixed(1)} s`;
}

function errorMessage(error: unknown): string | null {
  return error instanceof Error ? error.message : error ? "The recovery request failed." : null;
}

export function CommunicationConnectionDiagnostics({
  agentId,
  connection,
  canEdit,
}: {
  agentId: string;
  connection: CommunicationConnection;
  canEdit: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [reconnectOpen, setReconnectOpen] = useState(false);
  const [retryDeliveryId, setRetryDeliveryId] = useState<string | null>(null);
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
            <button
              type="button"
              className="af-btn af-btn-sm"
              aria-expanded={open}
              onClick={() => setOpen((current) => !current)}
            >
              {open ? <X size={14} /> : <RefreshCw size={14} />}
              {open ? "Hide diagnostics" : "Diagnostics"}
            </button>
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

                {diagnostics.data.recentFailures.length > 0 && (
                  <div className="rounded-lg p-3" style={{ border: "1px solid color-mix(in srgb, var(--err) 25%, var(--line))", background: "var(--bg-elev)" }}>
                    <div className="text-xs font-semibold" style={{ color: "var(--ink-2)" }}>Recent failures</div>
                    <div className="mt-2 flex flex-col gap-2">
                      {diagnostics.data.recentFailures.map((failure) => (
                        <div key={failure.id} className="flex flex-wrap items-center justify-between gap-2 text-xs">
                          <div className="min-w-0">
                            <span style={{ color: "var(--err)" }}>{failure.errorCode ?? failure.stage}</span>
                            <span className="ml-2" style={{ color: "var(--ink-4)" }}>{formatTimestamp(failure.occurredAt)}</span>
                            {failure.errorSummary && <div className="mt-0.5 truncate" style={{ color: "var(--ink-3)" }}>{failure.errorSummary}</div>}
                          </div>
                          {canEdit && failure.deliveryId && failure.stage === "dead_lettered" && (
                            <button
                              type="button"
                              className="af-btn af-btn-sm"
                              onClick={() => setRetryDeliveryId(failure.deliveryId)}
                            >
                              <RotateCcw size={13} /> Retry
                            </button>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <div className="rounded-lg p-3" style={{ border: "1px solid var(--line)", background: "var(--bg-elev)" }}>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="text-xs font-semibold" style={{ color: "var(--ink-2)" }}>Latest transitions</div>
                    <span className="text-[11px]" style={{ color: "var(--ink-4)" }}>Showing up to 50 · no message content</span>
                  </div>
                  <div className="mt-2 max-h-64 overflow-auto">
                    {diagnostics.data.latestTransitions.length === 0 ? (
                      <p className="m-0 text-xs" style={{ color: "var(--ink-4)" }}>No transitions in this window.</p>
                    ) : (
                      <div className="flex flex-col divide-y" style={{ borderColor: "var(--line)" }}>
                        {diagnostics.data.latestTransitions.map((transition) => (
                          <div key={transition.id} className="grid grid-cols-[1fr_auto] gap-3 py-2 text-xs first:pt-0 last:pb-0">
                            <div>
                              <span className="font-medium" style={{ color: "var(--ink-2)" }}>{transition.stage.replace(/_/g, " ")}</span>
                              {transition.disposition && <span className="ml-2" style={{ color: "var(--ink-4)" }}>{transition.disposition.replace(/_/g, " ")}</span>}
                              {transition.errorCode && <div className="mt-0.5" style={{ color: "var(--err)" }}>{transition.errorCode}</div>}
                            </div>
                            <div className="text-right" style={{ color: "var(--ink-4)" }}>
                              <div>{formatTimestamp(transition.occurredAt)}</div>
                              <div>attempt {transition.attemptNumber} · {formatDuration(transition.durationMs)}</div>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>

                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="text-xs" style={{ color: "var(--ink-4)" }}>Last checked {formatTimestamp(diagnostics.data.windowEnd)}</div>
                  <button type="button" className="af-btn af-btn-sm" onClick={() => void diagnostics.refetch()}>
                    <RefreshCw size={13} /> Refresh
                  </button>
                </div>
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
