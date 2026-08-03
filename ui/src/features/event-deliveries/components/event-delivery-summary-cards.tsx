"use client";

import type { ReactNode } from "react";

import { Skeleton } from "@/components/ui/skeleton";

import { EVENT_DELIVERY_STATUS_LABELS } from "../constants";
import { formatAgeSeconds } from "../format";
import type { EventDeliveryActiveStateStats, EventDeliveryStatus, EventDeliverySummary } from "../schemas";

interface EventDeliverySummaryCardsProps {
  summary: EventDeliverySummary | undefined;
  isLoading: boolean;
  activeStatus: EventDeliveryStatus | undefined;
  onSelectStatus: (status: EventDeliveryStatus) => void;
}

const ACTIVE_STATES: EventDeliveryStatus[] = ["PENDING", "ENQUEUED", "PROCESSING"];

export function EventDeliverySummaryCards({
  summary,
  isLoading,
  activeStatus,
  onSelectStatus,
}: EventDeliverySummaryCardsProps) {
  if (isLoading || !summary) {
    return (
      <div
        data-testid="event-delivery-summary-skeleton"
        className="grid gap-3 mb-6"
        style={{ gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}
      >
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="af-card px-4 py-3.5">
            <Skeleton className="h-3 w-16 mb-2" />
            <Skeleton className="h-6 w-12" />
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="grid gap-3 mb-6" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}>
      {ACTIVE_STATES.map((status) => {
        const stats: EventDeliveryActiveStateStats = summary[status.toLowerCase() as "pending" | "enqueued" | "processing"];
        const needsAttention = stats.staleCount > 0 || stats.unknownAgeCount > 0;
        return (
          <StateCard
            key={status}
            label={EVENT_DELIVERY_STATUS_LABELS[status]}
            count={stats.count}
            selected={activeStatus === status}
            attention={needsAttention}
            onClick={() => onSelectStatus(status)}
            detail={
              <>
                Stale {stats.staleCount} · Unknown age {stats.unknownAgeCount}
                <br />
                Oldest {formatAgeSeconds(stats.oldestAgeSeconds)}
              </>
            }
          />
        );
      })}

      <StateCard
        label={EVENT_DELIVERY_STATUS_LABELS.SUCCEEDED}
        count={summary.statusCounts.succeeded}
        selected={activeStatus === "SUCCEEDED"}
        attention={false}
        onClick={() => onSelectStatus("SUCCEEDED")}
        detail={<>Informational only</>}
      />

      <StateCard
        label={EVENT_DELIVERY_STATUS_LABELS.DEAD_LETTERED}
        count={summary.statusCounts.deadLettered}
        selected={activeStatus === "DEAD_LETTERED"}
        attention={summary.statusCounts.deadLettered > 0}
        failure
        onClick={() => onSelectStatus("DEAD_LETTERED")}
        detail={<>Terminal failures</>}
      />
    </div>
  );
}

function StateCard({
  label,
  count,
  selected,
  attention,
  failure,
  detail,
  onClick,
}: {
  label: string;
  count: number;
  selected: boolean;
  attention: boolean;
  failure?: boolean;
  detail: ReactNode;
  onClick: () => void;
}) {
  const accentColor = failure ? "var(--err)" : attention ? "var(--warn)" : "var(--ink)";
  return (
    <button
      type="button"
      onClick={onClick}
      className="af-card af-card-hover px-4 py-3.5 text-left"
      style={{
        borderColor: selected ? accentColor : undefined,
        boxShadow: selected ? `0 0 0 1px ${accentColor}` : undefined,
      }}
    >
      <div className="text-[12px] font-medium mb-1" style={{ color: "var(--ink-3)" }}>
        {label}
      </div>
      <div className="text-[22px] font-semibold mb-1" style={{ color: accentColor }}>
        {count.toLocaleString()}
      </div>
      <div className="text-[11.5px] leading-[1.4]" style={{ color: "var(--ink-4)" }}>
        {detail}
      </div>
    </button>
  );
}
