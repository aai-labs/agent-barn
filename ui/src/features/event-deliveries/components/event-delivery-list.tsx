"use client";

import { SearchX, Waypoints } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { Skeleton } from "@/components/ui/skeleton";

import type { EventDelivery } from "../schemas";
import { EventDeliveryRow } from "./event-delivery-row";

const ROW_GRID_HEADER =
  "grid-cols-[28px_130px_minmax(160px,1.3fr)_minmax(140px,1fr)_minmax(140px,1fr)_90px_70px]";

interface EventDeliveryListProps {
  deliveries: EventDelivery[];
  isLoading: boolean;
  error: unknown;
  onRetry: () => void;
  expandedId: string | null;
  onToggleExpand: (id: string) => void;
  hasActiveFilters: boolean;
}

export function EventDeliveryList({
  deliveries,
  isLoading,
  error,
  onRetry,
  expandedId,
  onToggleExpand,
  hasActiveFilters,
}: EventDeliveryListProps) {
  if (isLoading) {
    return (
      <div data-testid="event-delivery-list-skeleton" className="af-card overflow-hidden" style={{ padding: 0 }}>
        <div className={`grid ${ROW_GRID_HEADER} border-b px-3 py-2`} style={{ borderColor: "var(--line)" }}>
          <div />
          {["Status", "Event", "Organization", "Handler", "Age", "Attempts"].map((label) => (
            <div key={label} className="text-[11px] font-medium" style={{ color: "var(--ink-4)" }}>
              {label}
            </div>
          ))}
        </div>
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="px-3 py-2.5" style={{ borderTop: i > 0 ? "1px solid var(--line)" : undefined }}>
            <Skeleton className="h-4 w-full" />
          </div>
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <AppErrorState
        error={error}
        title="Failed to load Event Deliveries"
        onRetry={onRetry}
        className="min-h-[240px] p-0"
      />
    );
  }

  if (deliveries.length === 0) {
    return (
      <div
        className="flex flex-col items-center justify-center text-center py-16 rounded-2xl gap-2"
        style={{ border: "1px dashed var(--line-strong)" }}
      >
        {hasActiveFilters ? <SearchX size={20} style={{ color: "var(--ink-4)" }} /> : <Waypoints size={20} style={{ color: "var(--ink-4)" }} />}
        <div className="font-medium text-[15px]" style={{ color: "var(--ink)" }}>
          {hasActiveFilters ? "No matching Event Deliveries" : "No Event Deliveries yet"}
        </div>
        <div className="text-[13.5px]" style={{ color: "var(--ink-3)" }}>
          {hasActiveFilters
            ? "Try changing the search, filters, or date range."
            : "Event Deliveries appear here once handlers are registered for an emitted Domain Event."}
        </div>
      </div>
    );
  }

  return (
    <div className="af-card overflow-hidden" style={{ padding: 0 }}>
      <div className={`grid ${ROW_GRID_HEADER} border-b px-3 py-2`} style={{ borderColor: "var(--line)" }}>
        <div />
        {["Status", "Event", "Organization", "Handler", "Age", "Attempts"].map((label) => (
          <div key={label} className="text-[11px] font-medium" style={{ color: "var(--ink-4)" }}>
            {label}
          </div>
        ))}
      </div>
      {deliveries.map((delivery) => (
        <EventDeliveryRow
          key={delivery.id}
          delivery={delivery}
          expanded={expandedId === delivery.id}
          onToggle={() => onToggleExpand(delivery.id)}
        />
      ))}
    </div>
  );
}
