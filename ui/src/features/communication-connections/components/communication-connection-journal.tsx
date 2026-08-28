"use client";

import { useEffect, useState } from "react";
import { useWindowVirtualizer } from "@tanstack/react-virtual";
import { ArrowDownToLine, ArrowUpFromLine, Check, ChevronDown, ChevronRight, CircleDot, Copy, Loader2, Waypoints } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { useCommunicationConnectionJournal } from "@/features/communication-connections/hooks/use-communication-connections";
import type { CommunicationJournalEntry, CommunicationJournalKind } from "@/features/communication-connections/schemas";

const DELIVERY_ROW_GRID = "grid-cols-[28px_minmax(160px,1fr)_110px_130px_110px_130px_70px]";
const CONNECTION_ROW_GRID = "grid-cols-[28px_minmax(160px,1fr)_130px_110px_130px_70px]";
const DELIVERY_HEADINGS = ["Stage", "Direction", "Status", "Duration", "Occurred", "Attempt"];
const CONNECTION_HEADINGS = ["Stage", "Status", "Duration", "Occurred", "Attempt"];

const CONNECTION_STAGE_STATUS: Record<string, { label: string; color: string }> = {
  connection_connected: { label: "Connected", color: "var(--ok)" },
  connection_connecting: { label: "Connecting", color: "var(--warn)" },
  connection_degraded: { label: "Degraded", color: "var(--warn)" },
  connection_error: { label: "Error", color: "var(--err)" },
  reconnect_requested: { label: "Reconnecting", color: "var(--warn)" },
};

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

function label(value: string): string {
  return value.replace(/_/g, " ");
}

function statusColor(status: string): string {
  if (status === "SUCCEEDED") return "var(--ok)";
  if (status === "DEAD_LETTERED" || status === "UNAVAILABLE") return "var(--err)";
  if (status === "PROCESSING" || status === "PENDING") return "var(--warn)";
  return "var(--ink-4)";
}

export function CommunicationConnectionJournal({
  agentId,
  connectionId,
  kind,
  canEdit,
  lastCheckedAt,
  onRetryDelivery,
}: {
  agentId: string;
  connectionId: string;
  kind: CommunicationJournalKind;
  canEdit: boolean;
  lastCheckedAt: string;
  onRetryDelivery: (deliveryId: string) => void;
}) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [scrollMargin, setScrollMargin] = useState(0);
  const journal = useCommunicationConnectionJournal(agentId, connectionId, kind);
  const { entries, fetchNextPage, hasNextPage, isFetchingNextPage, isFetchingNextPageError } = journal;
  const virtualRowCount = hasNextPage ? entries.length + 1 : entries.length;
  const rowVirtualizer = useWindowVirtualizer({
    count: virtualRowCount,
    estimateSize: () => 44,
    overscan: 8,
    scrollMargin,
  });
  const virtualRows = rowVirtualizer.getVirtualItems();

  useEffect(() => {
    const lastVirtualRow = virtualRows.at(-1);
    if (
      lastVirtualRow
      && lastVirtualRow.index >= entries.length - 1
      && hasNextPage
      && !isFetchingNextPage
      && !isFetchingNextPageError
    ) {
      void fetchNextPage();
    }
  }, [entries.length, fetchNextPage, hasNextPage, isFetchingNextPage, isFetchingNextPageError, virtualRows]);

  if (journal.isLoading) {
    return <JournalSkeleton />;
  }

  if (journal.error) {
    return <AppErrorState error={journal.error} title="Failed to load connection activity" onRetry={() => void journal.refetch()} />;
  }

  const isDelivery = kind === "delivery";
  const rowGrid = isDelivery ? DELIVERY_ROW_GRID : CONNECTION_ROW_GRID;
  const headings = isDelivery ? DELIVERY_HEADINGS : CONNECTION_HEADINGS;

  const header = (
    <div className="mb-3 flex items-center justify-between gap-3">
      <span className="text-[13px]" style={{ color: "var(--ink-4)" }}>{journal.total.toLocaleString()} {journal.total === 1 ? "event" : "events"}</span>
      <span className="text-[13px]" style={{ color: "var(--ink-4)" }}>Last checked {formatTimestamp(lastCheckedAt)}</span>
    </div>
  );

  if (journal.entries.length === 0) {
    return (
      <section>
        {header}
        <div className="flex flex-col items-center justify-center gap-2 rounded-2xl py-16 text-center" style={{ border: "1px dashed var(--line-strong)" }}>
          <Waypoints size={20} style={{ color: "var(--ink-4)" }} />
          <div className="text-[15px] font-medium" style={{ color: "var(--ink)" }}>No {kind === "delivery" ? "delivery transitions" : "connection events"} yet</div>
          <div className="text-[13.5px]" style={{ color: "var(--ink-3)" }}>{kind === "delivery" ? "Delivery transitions appear once this connection receives or sends messages." : "Connection events appear when the provider connects, reconnects, or reports an error."}</div>
        </div>
      </section>
    );
  }

  return (
    <section>
      {header}
      <div className="af-card overflow-hidden" style={{ padding: 0 }}>
        <div className={`grid ${rowGrid} border-b px-3 py-2`} style={{ borderColor: "var(--line)" }}>
          <div />
          {headings.map((heading) => (
            <div key={heading} className="text-[11px] font-medium" style={{ color: "var(--ink-4)" }}>{heading}</div>
          ))}
        </div>
        <div ref={(node) => setScrollMargin(node?.offsetTop ?? 0)} style={{ height: rowVirtualizer.getTotalSize(), position: "relative" }}>
          {virtualRows.map((virtualRow) => {
            const isLoaderRow = virtualRow.index >= journal.entries.length;
            const entry = journal.entries[virtualRow.index];
            return (
              <div
                key={isLoaderRow ? "loader" : entry.id}
                data-index={virtualRow.index}
                ref={rowVirtualizer.measureElement}
                className="absolute left-0 top-0 w-full"
                style={{ transform: `translateY(${virtualRow.start - rowVirtualizer.options.scrollMargin}px)` }}
              >
                {isLoaderRow ? (
                  <div className="flex items-center justify-center gap-2 py-6 text-[13px]" style={{ color: "var(--ink-4)" }}>
                    {journal.isFetchingNextPage ? <><Loader2 size={15} className="animate-spin" /> Loading more activity…</> : "Scroll to load more activity"}
                  </div>
                ) : (
                  <JournalRow
                    entry={entry}
                    expanded={expandedId === entry.id}
                    onToggle={() => setExpandedId((current) => current === entry.id ? null : entry.id)}
                    canEdit={canEdit}
                    onRetryDelivery={onRetryDelivery}
                    rowGrid={rowGrid}
                    showDeliveryColumns={isDelivery}
                  />
                )}
              </div>
            );
          })}
        </div>
      </div>
      {journal.isFetchingNextPageError && (
        <p className="py-4 text-center text-[13px]" style={{ color: "var(--err)" }}>
          Unable to load more activity. <button type="button" className="underline" onClick={() => void journal.fetchNextPage()}>Try again</button>
        </p>
      )}
    </section>
  );
}

function JournalRow({ entry, expanded, onToggle, canEdit, onRetryDelivery, rowGrid, showDeliveryColumns }: { entry: CommunicationJournalEntry; expanded: boolean; onToggle: () => void; canEdit: boolean; onRetryDelivery: (deliveryId: string) => void; rowGrid: string; showDeliveryColumns: boolean }) {
  return (
    <div style={{ borderTop: "1px solid var(--line)" }}>
      <button type="button" onClick={onToggle} className={`grid ${rowGrid} w-full items-center px-3 py-2.5 text-left text-[0.8125rem] af-hover-bg`}>
        <span style={{ color: "var(--ink-4)" }}>{expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</span>
        <span className="truncate capitalize" style={{ color: "var(--ink)" }}>{label(entry.stage)}</span>
        {showDeliveryColumns && <span>{entry.direction && <DirectionBadge direction={entry.direction} />}</span>}
        <span>
          {entry.deliveryStatus ? <StatusBadge status={entry.deliveryStatus} /> : <ConnectionStatusBadge stage={entry.stage} />}
        </span>
        <span style={{ color: "var(--ink-3)" }}>{formatDuration(entry.durationMs)}</span>
        <span style={{ color: "var(--ink-3)" }}>{formatTimestamp(entry.occurredAt)}</span>
        <span style={{ color: "var(--ink-3)" }}>{entry.attemptNumber}</span>
      </button>
      {expanded && <JournalDetail entry={entry} canEdit={canEdit} onRetryDelivery={onRetryDelivery} />}
    </div>
  );
}

function DirectionBadge({ direction }: { direction: "INBOUND" | "OUTBOUND" }) {
  const isInbound = direction === "INBOUND";
  return (
    <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium" style={{ background: "var(--bg-soft)", color: "var(--ink-2)" }}>
      {isInbound ? <ArrowDownToLine size={12} /> : <ArrowUpFromLine size={12} />}
      {isInbound ? "Inbound" : "Outbound"}
    </span>
  );
}

function StatusBadge({ status }: { status: "PENDING" | "PROCESSING" | "SUCCEEDED" | "DEAD_LETTERED" | "CANCELLED" | "UNAVAILABLE" }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] font-medium capitalize" style={{ color: statusColor(status) }}>
      <CircleDot size={12} />{label(status)}
    </span>
  );
}

function ConnectionStatusBadge({ stage }: { stage: string }) {
  const status = CONNECTION_STAGE_STATUS[stage] ?? { label: label(stage), color: "var(--ink-4)" };
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] font-medium capitalize" style={{ color: status.color }}>
      <CircleDot size={12} />{status.label}
    </span>
  );
}

function JournalDetail({ entry, canEdit, onRetryDelivery }: { entry: CommunicationJournalEntry; canEdit: boolean; onRetryDelivery: (deliveryId: string) => void }) {
  const [copied, setCopied] = useState(false);
  const error = [entry.errorCode, entry.errorSummary].filter(Boolean).join(": ");

  async function copyError() {
    if (!error) return;
    await navigator.clipboard.writeText(error);
    setCopied(true);
  }

  return (
    <div className="space-y-4 px-10 py-4" style={{ background: "var(--bg-soft)" }}>
      <DetailSection title="Activity">
        <DetailRow label="Stage" value={label(entry.stage)} />
        {entry.disposition && <DetailRow label="Disposition" value={label(entry.disposition)} />}
        {entry.direction && <DetailRow label="Direction" value={label(entry.direction)} />}
        {entry.deliveryStatus && <DetailRow label="Current status" value={label(entry.deliveryStatus)} />}
        <DetailRow label="Delivery ID" value={entry.deliveryId ?? "—"} mono />
        <DetailRow label="Occurred at" value={formatTimestamp(entry.occurredAt)} />
        <DetailRow label="Attempt" value={entry.attemptNumber} />
        <DetailRow label="Duration" value={formatDuration(entry.durationMs)} />
      </DetailSection>
      {error && (
        <DetailSection title="Error">
          <div className="flex items-start justify-between gap-3 px-3 py-2.5 text-[13px]" style={{ color: "var(--err)" }}>
            <span className="min-w-0 break-words">{error}</span>
            <button type="button" className="af-btn af-btn-sm flex-shrink-0" aria-label={`Copy error for ${label(entry.stage)}`} onClick={() => void copyError()}>
              {copied ? <Check size={13} /> : <Copy size={13} />}{copied ? "Copied" : "Copy"}
            </button>
          </div>
        </DetailSection>
      )}
      {canEdit && entry.deliveryId && entry.stage === "dead_lettered" && (
        <button type="button" className="af-btn af-btn-sm" onClick={() => onRetryDelivery(entry.deliveryId!)}>Retry delivery</button>
      )}
    </div>
  );
}

function DetailSection({ title, children }: { title: string; children: React.ReactNode }) {
  return <section><h3 className="mb-2 text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--ink-4)" }}>{title}</h3><div className="divide-y rounded-lg" style={{ border: "1px solid var(--line)", background: "var(--bg)" }}>{children}</div></section>;
}

function DetailRow({ label: rowLabel, value, mono = false }: { label: string; value: string | number; mono?: boolean }) {
  return <div className="grid grid-cols-[140px_1fr] gap-4 px-3 py-2 text-[13px]"><span style={{ color: "var(--ink-4)" }}>{rowLabel}</span><span className={mono ? "break-all font-mono text-xs" : "break-words"} style={{ color: "var(--ink-2)" }}>{value}</span></div>;
}

function JournalSkeleton() {
  return <div className="af-card overflow-hidden" style={{ padding: 0 }}>{Array.from({ length: 7 }).map((_, index) => <div key={index} className="px-3 py-2.5" style={{ borderTop: index ? "1px solid var(--line)" : undefined }}><Skeleton className="h-4 w-full" /></div>)}</div>;
}
