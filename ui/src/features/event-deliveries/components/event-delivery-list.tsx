"use client";

import { useEffect, useState } from "react";
import { useWindowVirtualizer } from "@tanstack/react-virtual";
import { Loader2, SearchX, Waypoints } from "lucide-react";

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
  hasNextPage: boolean;
  fetchNextPage: () => void;
  isFetchingNextPage: boolean;
  isFetchingNextPageError: boolean;
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
  fetchNextPage,
  isFetchingNextPage,
  isFetchingNextPageError,
}: EventDeliveryListProps) {
  const [scrollMargin, setScrollMargin] = useState(0);
  const virtualRowCount = hasNextPage
    ? deliveries.length + 1
    : deliveries.length;
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
      lastVirtualRow &&
      lastVirtualRow.index >= deliveries.length - 1 &&
      hasNextPage &&
      !isFetchingNextPage &&
      !isFetchingNextPageError
    ) {
      fetchNextPage();
    }
  }, [
    deliveries.length,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isFetchingNextPageError,
    virtualRows,
  ]);

  if (isLoading) {
    return (
      <div
        data-testid="event-delivery-list-skeleton"
        className="af-card overflow-hidden"
        style={{ padding: 0 }}
      >
        <div
          className={`grid ${ROW_GRID_HEADER} border-b px-3 py-2`}
          style={{ borderColor: "var(--line)" }}
        >
          <div />
          {[
            "Status",
            "Event",
            "Organization",
            "Handler",
            "Age",
            "Attempts",
          ].map((label) => (
            <div
              key={label}
              className="text-[11px] font-medium"
              style={{ color: "var(--ink-4)" }}
            >
              {label}
            </div>
          ))}
        </div>
        {Array.from({ length: 8 }).map((_, i) => (
          <div
            key={i}
            className="px-3 py-2.5"
            style={{ borderTop: i > 0 ? "1px solid var(--line)" : undefined }}
          >
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
        {hasActiveFilters ? (
          <SearchX size={20} style={{ color: "var(--ink-4)" }} />
        ) : (
          <Waypoints size={20} style={{ color: "var(--ink-4)" }} />
        )}
        <div
          className="font-medium text-[15px]"
          style={{ color: "var(--ink)" }}
        >
          {hasActiveFilters
            ? "No matching Event Deliveries"
            : "No Event Deliveries yet"}
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
      <div
        className={`grid ${ROW_GRID_HEADER} border-b px-3 py-2`}
        style={{ borderColor: "var(--line)" }}
      >
        <div />
        {["Status", "Event", "Organization", "Handler", "Age", "Attempts"].map(
          (label) => (
            <div
              key={label}
              className="text-[11px] font-medium"
              style={{ color: "var(--ink-4)" }}
            >
              {label}
            </div>
          ),
        )}
      </div>
      <div
        ref={(node) => setScrollMargin(node?.offsetTop ?? 0)}
        style={{ height: rowVirtualizer.getTotalSize(), position: "relative" }}
      >
        {virtualRows.map((virtualRow) => {
          const isLoaderRow = virtualRow.index >= deliveries.length;
          const delivery = deliveries[virtualRow.index];

          return (
            <div
              key={isLoaderRow ? "loader" : delivery.id}
              data-index={virtualRow.index}
              ref={rowVirtualizer.measureElement}
              className="absolute left-0 top-0 w-full"
              style={{
                transform: `translateY(${virtualRow.start - rowVirtualizer.options.scrollMargin}px)`,
              }}
            >
              {isLoaderRow ? (
                <div
                  className="flex items-center justify-center gap-2 py-6 text-[13px]"
                  style={{ color: "var(--ink-4)" }}
                >
                  {isFetchingNextPage ? (
                    <>
                      <Loader2 size={15} className="animate-spin" /> Loading more
                      deliveries…
                    </>
                  ) : (
                    "Scroll to load more deliveries"
                  )}
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
  );
}
