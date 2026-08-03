"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useWindowVirtualizer } from "@tanstack/react-virtual";
import { SearchX, Waypoints } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { Skeleton } from "@/components/ui/skeleton";

import type { EventDelivery } from "../schemas";
import { EventDeliveryRow } from "./event-delivery-row";

const ROW_GRID_HEADER =
  "grid-cols-[28px_130px_minmax(160px,1.3fr)_minmax(140px,1fr)_minmax(140px,1fr)_90px_70px]";

interface EventDeliveryListProps {
  deliveries: EventDelivery[];
  hasNextPage: boolean | undefined;
  isFetchingNextPage: boolean;
  fetchNextPage: () => void;
  isLoading: boolean;
  error: unknown;
  onRetry: () => void;
  expandedId: string | null;
  onToggleExpand: (id: string) => void;
  hasActiveFilters: boolean;
  scrollToTopSignal: number;
}

export function EventDeliveryList({
  deliveries,
  hasNextPage,
  isFetchingNextPage,
  fetchNextPage,
  isLoading,
  error,
  onRetry,
  expandedId,
  onToggleExpand,
  hasActiveFilters,
  scrollToTopSignal,
}: EventDeliveryListProps) {
  const listRef = useRef<HTMLDivElement>(null);
  const [scrollMargin, setScrollMargin] = useState(0);

  // Deliberately no dependency array: this must re-measure after every commit, not
  // just on mount, since content above this list (summary cards, filter bar) can
  // resize as data loads and shift the list's offset from the top of the page.
  // setScrollMargin bails out when the value is unchanged, so this doesn't loop.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useLayoutEffect(() => {
    setScrollMargin(listRef.current?.offsetTop ?? 0);
  });

  // Virtualize against the window's own scroll instead of an inner scroll
  // container, so the page shows exactly one scrollbar (the browser's) and the
  // list simply grows with its content.
  const rowVirtualizer = useWindowVirtualizer({
    count: deliveries.length,
    estimateSize: () => 44,
    overscan: 8,
    scrollMargin,
  });

  useEffect(() => {
    // Manual refresh should reliably return the explorer to the top, regardless of
    // how far the admin had scrolled before clicking Refresh.
    window.scrollTo({ top: 0 });
  }, [scrollToTopSignal]);

  const virtualItems = rowVirtualizer.getVirtualItems();
  const lastItem = virtualItems.at(-1);

  useEffect(() => {
    if (!lastItem) return;
    if (lastItem.index >= deliveries.length - 1 && hasNextPage && !isFetchingNextPage) {
      fetchNextPage();
    }
  }, [lastItem, deliveries.length, hasNextPage, isFetchingNextPage, fetchNextPage]);

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
    <div ref={listRef} className="af-card overflow-hidden" style={{ padding: 0 }}>
      <div className={`grid ${ROW_GRID_HEADER} border-b px-3 py-2`} style={{ borderColor: "var(--line)" }}>
        <div />
        {["Status", "Event", "Organization", "Handler", "Age", "Attempts"].map((label) => (
          <div key={label} className="text-[11px] font-medium" style={{ color: "var(--ink-4)" }}>
            {label}
          </div>
        ))}
      </div>
      <div style={{ height: rowVirtualizer.getTotalSize(), position: "relative" }}>
        {virtualItems.map((virtualRow) => {
          const delivery = deliveries[virtualRow.index];
          return (
            <div
              key={delivery.id}
              data-index={virtualRow.index}
              ref={rowVirtualizer.measureElement}
              style={{
                position: "absolute",
                top: 0,
                left: 0,
                width: "100%",
                transform: `translateY(${virtualRow.start - rowVirtualizer.options.scrollMargin}px)`,
              }}
            >
              <EventDeliveryRow
                delivery={delivery}
                expanded={expandedId === delivery.id}
                onToggle={() => onToggleExpand(delivery.id)}
              />
            </div>
          );
        })}
      </div>
      {isFetchingNextPage && (
        <p className="border-t px-3 py-2 text-xs" style={{ borderColor: "var(--line)", color: "var(--ink-4)" }}>
          Loading more Event Deliveries...
        </p>
      )}
    </div>
  );
}
