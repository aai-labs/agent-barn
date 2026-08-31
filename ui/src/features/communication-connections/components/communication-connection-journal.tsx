"use client";

import { useEffect, useState } from "react";
import { useWindowVirtualizer } from "@tanstack/react-virtual";
import {
  ArrowDownToLine,
  ArrowUpFromLine,
  Check,
  ChevronDown,
  ChevronRight,
  CircleDot,
  Copy,
  ListTree,
  Loader2,
  Waypoints,
} from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  useCommunicationConnectionJournal,
  useCommunicationDeliveryLifecycle,
} from "@/features/communication-connections/hooks/use-communication-connections";
import {
  CONNECTION_JOURNAL_STAGES,
  DELIVERY_JOURNAL_STAGES,
  type CommunicationJournalEntry,
  type CommunicationJournalFilters,
  type CommunicationJournalKind,
  type CommunicationJournalWindow,
} from "@/features/communication-connections/schemas";

const DELIVERY_ROW_GRID = "grid-cols-[28px_minmax(160px,1fr)_110px_130px_110px_130px_70px]";
const CONNECTION_ROW_GRID = "grid-cols-[28px_minmax(160px,1fr)_130px_110px_160px]";
const DELIVERY_HEADINGS = ["Stage", "Direction", "Current status", "Elapsed", "Occurred", "Attempt"];
const CONNECTION_HEADINGS = ["Stage", "Status", "Since previous", "Occurred"];

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
    second: "2-digit",
  });
}

function formatDuration(value: number | null): string {
  if (value === null) return "—";
  if (value < 1000) return `${Math.round(value)} ms`;
  return `${(value / 1000).toFixed(1)} s`;
}

function label(value: string): string {
  return value.replace(/_/g, " ").toLowerCase();
}

type JournalFilters = Omit<CommunicationJournalFilters, "since" | "until">;

function hasActiveFilters(filters: JournalFilters): boolean {
  return Boolean(
    filters.stage || filters.failedOnly || filters.retryableOnly || filters.direction || filters.deliveryId,
  );
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
  timeRange,
  lastCheckedAt,
  onRetryDelivery,
}: {
  agentId: string;
  connectionId: string;
  kind: CommunicationJournalKind;
  canEdit: boolean;
  timeRange: CommunicationJournalWindow;
  lastCheckedAt: string | null;
  onRetryDelivery: (deliveryId: string) => void;
}) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [scrollMargin, setScrollMargin] = useState(0);
  const [filters, setFilters] = useState<JournalFilters>({});
  const journal = useCommunicationConnectionJournal(agentId, connectionId, kind, { ...filters, ...timeRange });
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

  function handleFiltersChange(next: JournalFilters) {
    setExpandedId(null);
    setFilters(next);
  }

  const isDelivery = kind === "delivery";
  const rowGrid = isDelivery ? DELIVERY_ROW_GRID : CONNECTION_ROW_GRID;
  const headings = isDelivery ? DELIVERY_HEADINGS : CONNECTION_HEADINGS;
  const filtersActive = hasActiveFilters(filters);

  const header = (
    <div className="mb-3 flex items-center justify-between gap-3">
      <span className="text-[13px]" style={{ color: "var(--ink-4)" }}>{journal.total.toLocaleString()} {journal.total === 1 ? "event" : "events"}</span>
      {lastCheckedAt && <span className="text-[13px]" style={{ color: "var(--ink-4)" }}>Updated {formatTimestamp(lastCheckedAt)}</span>}
    </div>
  );

  const filterBar = (
    <CommunicationJournalFilterBar kind={kind} filters={filters} onChange={handleFiltersChange} />
  );

  if (journal.isLoading) {
    return (
      <section data-activity-kind={kind}>
        {header}
        {filterBar}
        <JournalSkeleton />
      </section>
    );
  }

  if (journal.error) {
    return (
      <section data-activity-kind={kind}>
        {header}
        {filterBar}
        <AppErrorState error={journal.error} title="Failed to load connection activity" onRetry={() => void journal.refetch()} />
      </section>
    );
  }

  if (journal.entries.length === 0) {
    return (
      <section data-activity-kind={kind}>
        {header}
        {filterBar}
        <div className="flex flex-col items-center justify-center gap-2 rounded-2xl py-16 text-center" style={{ border: "1px dashed var(--line-strong)" }}>
          <Waypoints size={20} style={{ color: "var(--ink-4)" }} />
          <div className="text-[15px] font-medium" style={{ color: "var(--ink)" }}>
            {filtersActive ? "No activity matches these filters" : `No ${kind === "delivery" ? "delivery transitions" : "technical events"} yet`}
          </div>
          <div className="text-[13.5px]" style={{ color: "var(--ink-3)" }}>{filtersActive ? "Try widening the time range or clearing a filter." : (kind === "delivery" ? "Delivery transitions appear once this connection receives or sends messages." : "Technical events appear when the provider connects, reconnects, or reports an error.")}</div>
        </div>
      </section>
    );
  }

  return (
    <section data-activity-kind={kind}>
      {header}
      {filterBar}
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
                    agentId={agentId}
                    connectionId={connectionId}
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

function JournalRow({ entry, expanded, onToggle, canEdit, onRetryDelivery, agentId, connectionId, rowGrid, showDeliveryColumns }: { entry: CommunicationJournalEntry; expanded: boolean; onToggle: () => void; canEdit: boolean; onRetryDelivery: (deliveryId: string) => void; agentId: string; connectionId: string; rowGrid: string; showDeliveryColumns: boolean }) {
  const hasDetails = Boolean(entry.deliveryId)
    || Boolean(entry.disposition)
    || ["connection_error", "connection_degraded", "reconnect_requested"].includes(entry.stage);
  const row = (
    <>
      <span style={{ color: "var(--ink-4)" }}>
        {hasDetails && (expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />)}
      </span>
      <span className="truncate capitalize" style={{ color: "var(--ink)" }}>{label(entry.stage)}</span>
      {showDeliveryColumns && <span>{entry.direction && <DirectionBadge direction={entry.direction} />}</span>}
      <span>
        {entry.deliveryStatus ? <StatusBadge status={entry.deliveryStatus} /> : <ConnectionStatusBadge stage={entry.stage} />}
      </span>
      <span style={{ color: "var(--ink-3)" }}>{formatDuration(entry.durationMs)}</span>
      <span style={{ color: "var(--ink-3)" }}>{formatTimestamp(entry.occurredAt)}</span>
      {showDeliveryColumns && <span style={{ color: "var(--ink-3)" }}>{entry.attemptNumber}</span>}
    </>
  );

  return (
    <div style={{ borderTop: "1px solid var(--line)" }}>
      {hasDetails ? (
        <button type="button" onClick={onToggle} className={`grid ${rowGrid} w-full items-center px-3 py-2.5 text-left text-[0.8125rem] af-hover-bg`}>
          {row}
        </button>
      ) : (
        <div className={`grid ${rowGrid} w-full items-center px-3 py-2.5 text-left text-[0.8125rem]`}>
          {row}
        </div>
      )}
      {expanded && (
        <JournalDetail
          entry={entry}
          canEdit={canEdit}
          onRetryDelivery={onRetryDelivery}
          agentId={agentId}
          connectionId={connectionId}
        />
      )}
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

function JournalDetail({
  entry,
  canEdit,
  onRetryDelivery,
  agentId,
  connectionId,
}: {
  entry: CommunicationJournalEntry;
  canEdit: boolean;
  onRetryDelivery: (deliveryId: string) => void;
  agentId: string;
  connectionId: string;
}) {
  const [copiedField, setCopiedField] = useState<string | null>(null);
  const [timelineOpen, setTimelineOpen] = useState(false);
  const error = [entry.errorCode, entry.errorSummary].filter(Boolean).join(": ");

  async function copyValue(value: string, field: string) {
    await navigator.clipboard.writeText(value);
    setCopiedField(field);
  }

  return (
    <div className="space-y-4 px-10 py-4" style={{ background: "var(--bg-soft)" }}>
      <DetailSection title={entry.deliveryId ? "Delivery activity" : "Connection event"}>
        <DetailRow label="Stage" value={label(entry.stage)} />
        {entry.disposition && <DetailRow label="Admission outcome" value={label(entry.disposition)} />}
        {entry.direction && <DetailRow label="Direction" value={label(entry.direction)} />}
        {entry.deliveryStatus && <DetailRow label="Current status" value={label(entry.deliveryStatus)} />}
        {entry.deliveryId && (
          <CopyableDetailRow
            label="Delivery ID"
            value={entry.deliveryId}
            copied={copiedField === "delivery-id"}
            onCopy={() => void copyValue(entry.deliveryId!, "delivery-id")}
          />
        )}
        <DetailRow label="Occurred at" value={formatTimestamp(entry.occurredAt)} />
        {entry.deliveryId ? (
          <DetailRow label="Attempt" value={entry.attemptNumber} />
        ) : (
          <DetailRow label="Since previous event" value={formatDuration(entry.durationMs)} />
        )}
      </DetailSection>
      {entry.deliveryId && (
        <DetailSection title="Delivery timing">
          <DetailRow label="Wait before attempt" value={formatDuration(entry.queueWaitMs ?? null)} />
          <DetailRow label="Processing time" value={formatDuration(entry.processingMs ?? null)} />
          {entry.nextRetryAt && <DetailRow label="Next retry" value={formatTimestamp(entry.nextRetryAt)} />}
        </DetailSection>
      )}
      {error && (
        <DetailSection title="Error">
          <div className="flex items-start justify-between gap-3 px-3 py-2.5 text-[13px]" style={{ color: "var(--err)" }}>
            <span className="min-w-0 break-words">{error}</span>
            <button type="button" className="af-btn af-btn-sm flex-shrink-0" aria-label={`Copy error for ${label(entry.stage)}`} onClick={() => void copyValue(error, "error")}>
              {copiedField === "error" ? <Check size={13} /> : <Copy size={13} />}{copiedField === "error" ? "Copied" : "Copy"}
            </button>
          </div>
        </DetailSection>
      )}
      {entry.errorDetails && (
        <DetailSection title="Diagnostic details">
          <DetailRow label="Category" value={label(entry.errorDetails.category)} />
          <DetailRow label="Operation" value={label(entry.errorDetails.operation)} />
          {entry.errorDetails.httpStatus !== null && <DetailRow label="HTTP status" value={entry.errorDetails.httpStatus} />}
          <DetailRow label="Provider code" value={entry.errorDetails.providerCode ?? "—"} />
          <DetailRow label="Retryable" value={entry.errorDetails.retryable ? "Yes" : "No"} />
          {entry.errorDetails.retryAfterSeconds !== null && <DetailRow label="Retry after" value={`${entry.errorDetails.retryAfterSeconds}s`} />}
          {entry.errorDetails.requestId && <DetailRow label="Request ID" value={entry.errorDetails.requestId} mono />}
        </DetailSection>
      )}
      <div className="flex flex-wrap gap-2">
        {entry.deliveryId && (
          <button
            type="button"
            className="af-btn af-btn-sm"
            aria-expanded={timelineOpen}
            onClick={() => setTimelineOpen((current) => !current)}
          >
            <ListTree size={13} />
            {timelineOpen ? "Hide delivery timeline" : "View delivery timeline"}
            {timelineOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
          </button>
        )}
        {canEdit
          && entry.deliveryId
          && entry.direction === "OUTBOUND"
          && entry.stage === "dead_lettered"
          && entry.deliveryStatus === "DEAD_LETTERED"
          && (
            <button type="button" className="af-btn af-btn-sm" onClick={() => onRetryDelivery(entry.deliveryId!)}>Retry delivery</button>
          )}
      </div>
      {timelineOpen && entry.deliveryId && (
        <DeliveryTimeline agentId={agentId} connectionId={connectionId} deliveryId={entry.deliveryId} />
      )}
    </div>
  );
}

function DeliveryTimeline({ agentId, connectionId, deliveryId }: { agentId: string; connectionId: string; deliveryId: string }) {
  const lifecycle = useCommunicationDeliveryLifecycle(agentId, connectionId, deliveryId);
  const entries = lifecycle.entries;

  if (lifecycle.isPending) {
    return (
      <DetailSection title="Delivery timeline">
        <div className="space-y-2 p-3">{Array.from({ length: 3 }).map((_, index) => <Skeleton key={index} className="h-10 w-full" />)}</div>
      </DetailSection>
    );
  }

  if (lifecycle.error) {
    return (
      <DetailSection title="Delivery timeline">
        <div className="p-3">
          <AppErrorState error={lifecycle.error} title="Failed to load the delivery timeline" onRetry={() => void lifecycle.refetch()} />
        </div>
      </DetailSection>
    );
  }

  return (
    <DetailSection title="Delivery timeline">
      <ol className="p-3">
        {entries.map((item, index) => {
          const itemError = [item.errorCode, item.errorSummary].filter(Boolean).join(": ");
          const isLast = index === entries.length - 1;
          return (
            <li key={item.id} className="relative pb-4 pl-5 last:pb-0">
              {!isLast && (
                <span className="absolute top-3 bottom-0 left-[4px] w-px" style={{ background: "var(--line-strong)" }} />
              )}
              <span
                className="absolute top-1 left-0 h-2.5 w-2.5 rounded-full"
                style={{ background: timelineDotColor(item) }}
              />
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-[13px] font-medium capitalize" style={{ color: "var(--ink)" }}>{label(item.stage)}</span>
                <span className="text-[12px]" style={{ color: "var(--ink-4)" }}>{formatTimestamp(item.occurredAt)}</span>
              </div>
              <div className="mt-0.5 flex flex-wrap items-center gap-2 text-[12px]" style={{ color: "var(--ink-3)" }}>
                <span>Attempt {item.attemptNumber}</span>
                <span>·</span>
                <span>{formatDuration(item.durationMs)}</span>
                {isLast && item.deliveryStatus && (
                  <>
                    <span>·</span>
                    <span>Current</span>
                    <StatusBadge status={item.deliveryStatus} />
                  </>
                )}
              </div>
              {itemError && <p className="mt-1 mb-0 text-[12px]" style={{ color: "var(--err)" }}>{itemError}</p>}
            </li>
          );
        })}
      </ol>
    </DetailSection>
  );
}

function timelineDotColor(entry: CommunicationJournalEntry): string {
  if (entry.errorCode) return "var(--err)";
  if (entry.deliveryStatus) return statusColor(entry.deliveryStatus);
  return CONNECTION_STAGE_STATUS[entry.stage]?.color ?? "var(--ink-4)";
}

function DetailSection({ title, children }: { title: string; children: React.ReactNode }) {
  return <section><h3 className="mb-2 text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--ink-4)" }}>{title}</h3><div className="divide-y rounded-lg" style={{ border: "1px solid var(--line)", background: "var(--bg)" }}>{children}</div></section>;
}

function DetailRow({ label: rowLabel, value, mono = false }: { label: string; value: string | number; mono?: boolean }) {
  return <div className="grid grid-cols-[140px_1fr] gap-4 px-3 py-2 text-[13px]"><span style={{ color: "var(--ink-4)" }}>{rowLabel}</span><span className={mono ? "break-all font-mono text-xs" : "break-words"} style={{ color: "var(--ink-2)" }}>{value}</span></div>;
}

function CopyableDetailRow({
  label: rowLabel,
  value,
  copied,
  onCopy,
}: {
  label: string;
  value: string;
  copied: boolean;
  onCopy: () => void;
}) {
  return (
    <div className="grid grid-cols-[140px_1fr] gap-4 px-3 py-2 text-[13px]">
      <span style={{ color: "var(--ink-4)" }}>{rowLabel}</span>
      <span className="flex min-w-0 items-center gap-2" style={{ color: "var(--ink-2)" }}>
        <span className="min-w-0 break-all font-mono text-xs">{value}</span>
        <button type="button" className="af-btn af-btn-sm flex-shrink-0" aria-label={`Copy ${rowLabel.toLowerCase()}`} onClick={onCopy}>
          {copied ? <Check size={13} /> : <Copy size={13} />}{copied ? "Copied" : "Copy"}
        </button>
      </span>
    </div>
  );
}

function JournalSkeleton() {
  return <div className="af-card overflow-hidden" style={{ padding: 0 }}>{Array.from({ length: 7 }).map((_, index) => <div key={index} className="px-3 py-2.5" style={{ borderTop: index ? "1px solid var(--line)" : undefined }}><Skeleton className="h-4 w-full" /></div>)}</div>;
}

function CommunicationJournalFilterBar({
  kind,
  filters,
  onChange,
}: {
  kind: CommunicationJournalKind;
  filters: JournalFilters;
  onChange: (filters: JournalFilters) => void;
}) {
  const [deliveryIdInput, setDeliveryIdInput] = useState(filters.deliveryId ?? "");
  const isDelivery = kind === "delivery";
  const stages = isDelivery ? DELIVERY_JOURNAL_STAGES : CONNECTION_JOURNAL_STAGES;

  function applyDeliveryId() {
    const trimmed = deliveryIdInput.trim();
    onChange({ ...filters, deliveryId: trimmed || undefined });
  }

  return (
    <div className="mb-3 flex flex-wrap items-center gap-2">
      <Select
        value={filters.stage ?? "__all_stages__"}
        onValueChange={(value) => onChange({ ...filters, stage: value === "__all_stages__" ? undefined : value })}
      >
        <SelectTrigger className="w-[10.5rem]" aria-label="Filter by stage">
          <SelectValue placeholder="All stages" />
        </SelectTrigger>
        <SelectContent>
          <SelectGroup>
            <SelectItem value="__all_stages__">All stages</SelectItem>
            {stages.map((stage) => (
              <SelectItem key={stage} value={stage}>{label(stage)}</SelectItem>
            ))}
          </SelectGroup>
        </SelectContent>
      </Select>
      {isDelivery && (
        <Select
          value={filters.direction ?? "__any_direction__"}
          onValueChange={(value) => onChange({ ...filters, direction: value === "__any_direction__" ? undefined : value as "INBOUND" | "OUTBOUND" })}
        >
          <SelectTrigger className="w-[9rem]" aria-label="Filter by direction">
            <SelectValue placeholder="Any direction" />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectItem value="__any_direction__">Any direction</SelectItem>
              <SelectItem value="INBOUND">Inbound</SelectItem>
              <SelectItem value="OUTBOUND">Outbound</SelectItem>
            </SelectGroup>
          </SelectContent>
        </Select>
      )}
      {isDelivery && (
        <Input
          className="w-[13rem]"
          aria-label="Filter by delivery ID"
          placeholder="Delivery ID"
          value={deliveryIdInput}
          onChange={(event) => setDeliveryIdInput(event.target.value)}
          onBlur={applyDeliveryId}
          onKeyDown={(event) => { if (event.key === "Enter") applyDeliveryId(); }}
        />
      )}
      <Label className="h-8 gap-1.5 text-[13px] font-normal" style={{ color: "var(--ink-3)" }}>
        <Checkbox
          checked={Boolean(filters.failedOnly)}
          onCheckedChange={(checked) => onChange({ ...filters, failedOnly: checked === true || undefined })}
        />
        Failed only
      </Label>
      {isDelivery && (
        <Label className="h-8 gap-1.5 text-[13px] font-normal" style={{ color: "var(--ink-3)" }}>
          <Checkbox
            checked={Boolean(filters.retryableOnly)}
            onCheckedChange={(checked) => onChange({ ...filters, retryableOnly: checked === true || undefined })}
          />
          Retryable only
        </Label>
      )}
      {hasActiveFilters(filters) && (
        <Button type="button" variant="outline" onClick={() => { setDeliveryIdInput(""); onChange({}); }}>
          Clear filters
        </Button>
      )}
    </div>
  );
}
