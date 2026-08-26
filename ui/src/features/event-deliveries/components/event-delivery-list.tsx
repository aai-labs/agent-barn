"use client";

import { useEffect, useRef } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Loader2, SearchX, Waypoints } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { Skeleton } from "@/components/ui/skeleton";

import type { EventDelivery } from "../schemas";
import { EventDeliveryRow } from "./event-delivery-row";

const ROW_GRID_HEADER =
  "grid-cols-[28px_130px_minmax(160px,1.3fr)_minmax(140px,1fr)_minmax(140px,1fr)_90px_70px]";

const ESTIMATED_ROW_HEIGHT = 44;

interface EventDeliveryListProps {
  deliveries: EventDelivery[];
  isLoading: boolean;
  error: unknown;
  onRetry: () => void;
  expandedId: string | null;
  onToggleExpand: (id: string) => void;
  hasActiveFilters: boolean;
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  onLoadMore: () => void;
}

export function EventDeliveryList({
  deliveries,
  isLoading,
  error,
  onRetry,
  expandedId,
  onToggleExpand,
  hasActiveFilters,
  hasNextPage,
  isFetchingNextPage,
  onLoadMore,
}: EventDeliveryListProps) {
  const parentRef = useRef<HTMLDivElement>(null);
  const rowCount = hasNextPage ? deliveries.length + 1 : deliveries.length;

  const rowVirtualizer = useVirtualizer({
    count: rowCount,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ESTIMATED_ROW_HEIGHT,
    overscan: 8,
  });

  const virtualItems = rowVirtualizer.getVirtualItems();

  useEffect(() => {
    const lastItem = virtualItems[virtualItems.length - 1];
    if (!lastItem) return;
    if (lastItem.index >= deliveries.length - 1 && hasNextPage && !isFetchingNextPage) {
      onLoadMore();
    }
  }, [virtualItems, hasNextPage, isFetchingNextPage, onLoadMore, deliveries.length]);

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
      <div ref={parentRef} className="overflow-auto" style={{ maxHeight: "calc(100vh - 360px)" }}>
        <div style={{ height: rowVirtualizer.getTotalSize(), position: "relative", width: "100%" }}>
          {virtualItems.map((virtualRow) => {
            const isLoaderRow = virtualRow.index > deliveries.length - 1;
            const delivery = deliveries[virtualRow.index];

            return (
              <div
                key={virtualRow.key}
                data-index={virtualRow.index}
                ref={rowVirtualizer.measureElement}
                style={{
                  position: "absolute",
                  top: 0,
                  left: 0,
                  width: "100%",
                  transform: `translateY(${virtualRow.start}px)`,
                }}
              >
                {isLoaderRow ? (
                  <div
                    className="flex items-center justify-center gap-2 px-3 py-3 text-[13px]"
                    style={{ borderTop: "1px solid var(--line)", color: "var(--ink-4)" }}
                  >
                    <Loader2 size={14} className="animate-spin" /> Loading more…
                  </div>
                ) : (
                  <EventDeliveryRow
                    delivery={delivery}
                    expanded={expandedId === delivery.id}
                    onToggle={() => onToggleExpand(delivery.id)}
                  />
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
