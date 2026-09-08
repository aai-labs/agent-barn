"use client";

import { useEffect, useState } from "react";
import { useWindowVirtualizer } from "@tanstack/react-virtual";
import { Loader2, Receipt, SearchX } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { Skeleton } from "@/components/ui/skeleton";

import type { CostRecord, PlatformCostRecord } from "../schemas";
import { CostRow } from "./cost-row";

const ORG_GRID =
  "grid-cols-[150px_minmax(140px,1.2fr)_minmax(120px,1fr)_90px_90px_90px]";
const PLATFORM_GRID =
  "grid-cols-[150px_minmax(140px,1fr)_minmax(120px,1fr)_minmax(120px,1fr)_90px_90px_90px]";

interface CostListProps {
  records: (CostRecord | PlatformCostRecord)[];
  isLoading: boolean;
  error: unknown;
  onRetry: () => void;
  hasActiveFilters: boolean;
  hasNextPage: boolean;
  fetchNextPage: () => void;
  isFetchingNextPage: boolean;
  isFetchingNextPageError: boolean;
  /** Adds the organization column. Platform surface only. */
  showOrganization?: boolean;
}

export function CostList({
  records,
  isLoading,
  error,
  onRetry,
  hasActiveFilters,
  hasNextPage,
  fetchNextPage,
  isFetchingNextPage,
  isFetchingNextPageError,
  showOrganization = false,
}: CostListProps) {
  const [scrollMargin, setScrollMargin] = useState(0);
  const grid = showOrganization ? PLATFORM_GRID : ORG_GRID;

  const virtualRowCount = hasNextPage ? records.length + 1 : records.length;
  const rowVirtualizer = useWindowVirtualizer({
    count: virtualRowCount,
    estimateSize: () => 40,
    overscan: 8,
    scrollMargin,
  });
  const virtualRows = rowVirtualizer.getVirtualItems();

  useEffect(() => {
    const lastVirtualRow = virtualRows.at(-1);
    if (
      lastVirtualRow &&
      lastVirtualRow.index >= records.length - 1 &&
      hasNextPage &&
      !isFetchingNextPage &&
      !isFetchingNextPageError
    ) {
      fetchNextPage();
    }
  }, [
    records.length,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isFetchingNextPageError,
    virtualRows,
  ]);

  if (error) {
    return (
      <AppErrorState
        title="Unable to load costs"
        description="Something went wrong reading cost records."
        onRetry={onRetry}
      />
    );
  }

  if (isLoading) {
    return (
      <div data-testid="cost-list-skeleton" className="af-card overflow-hidden">
        <ListHeader grid={grid} showOrganization={showOrganization} />
        {Array.from({ length: 10 }).map((_, i) => (
          <div key={i} className="px-4 py-2.5 border-t" style={{ borderColor: "var(--line)" }}>
            <Skeleton className="h-4 w-full" />
          </div>
        ))}
      </div>
    );
  }

  if (records.length === 0) {
    return (
      <div
        className="af-card flex flex-col items-center justify-center py-16 text-center"
        data-testid="cost-list-empty"
      >
        {hasActiveFilters ? (
          <>
            <SearchX size={28} style={{ color: "var(--ink-4)" }} />
            <p className="mt-3 text-[14px]" style={{ color: "var(--ink-3)" }}>
              No calls match these filters.
            </p>
          </>
        ) : (
          <>
            <Receipt size={28} style={{ color: "var(--ink-4)" }} />
            <p className="mt-3 text-[14px]" style={{ color: "var(--ink-3)" }}>
              No LLM calls recorded in this period.
            </p>
            <p className="mt-1 text-[13px]" style={{ color: "var(--ink-4)" }}>
              Cost records arrive from the sync job, which runs every 15 minutes.
            </p>
          </>
        )}
      </div>
    );
  }

  return (
    <div
      className="af-card overflow-hidden"
      ref={(node) => {
        if (node) setScrollMargin(node.offsetTop);
      }}
      data-testid="cost-list"
    >
      <ListHeader grid={grid} showOrganization={showOrganization} />
      <div
        style={{ height: rowVirtualizer.getTotalSize(), position: "relative" }}
      >
        {virtualRows.map((virtualRow) => {
          const record = records[virtualRow.index];
          return (
            <div
              key={record?.requestId ?? `loader-${virtualRow.index}`}
              data-index={virtualRow.index}
              style={{
                position: "absolute",
                top: 0,
                left: 0,
                width: "100%",
                transform: `translateY(${virtualRow.start - rowVirtualizer.options.scrollMargin}px)`,
              }}
            >
              {record ? (
                <CostRow record={record} grid={grid} showOrganization={showOrganization} />
              ) : (
                <div className="flex items-center justify-center py-3">
                  <Loader2 size={16} className="animate-spin" style={{ color: "var(--ink-4)" }} />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ListHeader({
  grid,
  showOrganization,
}: {
  grid: string;
  showOrganization: boolean;
}) {
  return (
    <div
      className={`grid ${grid} gap-3 px-4 py-2.5 text-[12px] font-medium`}
      style={{ color: "var(--ink-4)", background: "var(--surface-2)" }}
    >
      <span>When</span>
      <span>Model</span>
      <span>Agent</span>
      {showOrganization && <span>Organization</span>}
      <span className="text-right">Tokens</span>
      <span className="text-right">Duration</span>
      <span className="text-right">Cost</span>
    </div>
  );
}
