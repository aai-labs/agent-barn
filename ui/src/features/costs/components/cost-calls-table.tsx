"use client";

import { Receipt, SearchX } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { Pagination } from "@/features/agents/components/pagination";

import type { CostRecord } from "../schemas";
import { CostSortSelect } from "./cost-filter-bar";
import { AGENT_GRID, ListHeader } from "./cost-list";
import { CostRow } from "./cost-row";

interface CostCallsTableProps {
  records: CostRecord[];
  total: number;
  page: number;
  pageSize: number;
  onPageChange: (page: number) => void;
  sort: string;
  onSortChange: (sort: string) => void;
  isLoading: boolean;
  /** A page change in flight while the previous page stays on screen. */
  isFetching: boolean;
  error: unknown;
  onRetry: () => void;
  hasActiveFilters: boolean;
}

/**
 * One Agent's calls, a page at a time.
 *
 * Paged rather than infinitely scrolled like the Organization list: this table
 * closes a long page of cards, charts and monthly totals, and a list that keeps
 * loading as it is scrolled would leave that page without an end. A fixed page
 * also keeps the table's height stable, so paging does not move anything above
 * it.
 */
export function CostCallsTable({
  records,
  total,
  page,
  pageSize,
  onPageChange,
  sort,
  onSortChange,
  isLoading,
  isFetching,
  error,
  onRetry,
  hasActiveFilters,
}: CostCallsTableProps) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const first = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const last = Math.min(page * pageSize, total);

  return (
    <section className="af-card overflow-hidden" data-testid="agent-calls">
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
        <div>
          <h2
            className="text-[14px] font-semibold m-0"
            style={{ color: "var(--ink)" }}
          >
            Calls
          </h2>
          <p
            className="text-[12px] m-0 mt-0.5"
            style={{ color: "var(--ink-4)" }}
            data-testid="agent-calls-range"
          >
            {isLoading
              ? "Loading…"
              : total === 0
                ? "No calls"
                : `Showing ${first.toLocaleString()}–${last.toLocaleString()} of ${total.toLocaleString()} ${total === 1 ? "call" : "calls"}`}
          </p>
        </div>
        <CostSortSelect value={sort} onChange={onSortChange} />
      </div>

      {error ? (
        <div className="border-t" style={{ borderColor: "var(--line)" }}>
          <AppErrorState
            title="Unable to load calls"
            description="Something went wrong reading this agent's calls."
            onRetry={onRetry}
            className="min-h-[12rem]"
          />
        </div>
      ) : isLoading ? (
        <>
          <ListHeader grid={AGENT_GRID} showOrganization={false} showAgent={false} />
          {Array.from({ length: pageSize }).map((_, i) => (
            <div
              key={i}
              className="px-4 py-2.5 border-t"
              style={{ borderColor: "var(--line)" }}
            >
              <Skeleton className="h-4 w-full" />
            </div>
          ))}
        </>
      ) : records.length === 0 ? (
        <div
          className="flex flex-col items-center justify-center border-t py-12 text-center"
          style={{ borderColor: "var(--line)" }}
          data-testid="agent-calls-empty"
        >
          {hasActiveFilters ? (
            <>
              <SearchX size={24} style={{ color: "var(--ink-4)" }} />
              <p className="mt-3 text-[14px]" style={{ color: "var(--ink-3)" }}>
                No calls match these filters.
              </p>
            </>
          ) : (
            <>
              <Receipt size={24} style={{ color: "var(--ink-4)" }} />
              <p className="mt-3 text-[14px]" style={{ color: "var(--ink-3)" }}>
                No LLM calls recorded in this period.
              </p>
              <p className="mt-1 text-[13px]" style={{ color: "var(--ink-4)" }}>
                Cost records arrive from the sync job, which runs every 15 minutes.
              </p>
            </>
          )}
        </div>
      ) : (
        <>
          <ListHeader grid={AGENT_GRID} showOrganization={false} showAgent={false} />
          {/* Dimmed rather than replaced while the next page loads, so the
              table keeps its height and the page does not jump. */}
          <div
            style={{ opacity: isFetching ? 0.55 : 1, transition: "opacity 120ms" }}
            aria-busy={isFetching}
          >
            {records.map((record) => (
              <CostRow
                key={record.requestId}
                record={record}
                grid={AGENT_GRID}
                showOrganization={false}
                showAgent={false}
              />
            ))}
          </div>
        </>
      )}

      {totalPages > 1 && !error && (
        <div
          className="border-t px-4 py-3"
          style={{ borderColor: "var(--line)" }}
        >
          <Pagination
            page={page}
            totalPages={totalPages}
            onPageChange={onPageChange}
            align="end"
          />
        </div>
      )}
    </section>
  );
}
