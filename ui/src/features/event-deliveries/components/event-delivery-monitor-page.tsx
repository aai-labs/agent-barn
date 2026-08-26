"use client";

import { useCallback, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { parseAsString, parseAsStringEnum, useQueryStates } from "nuqs";

import { useEventDeliveryEventTypes } from "../hooks/use-event-delivery-event-types";
import { useEventDeliverySummary } from "../hooks/use-event-delivery-summary";
import { useEventDeliveries } from "../hooks/use-event-deliveries";
import {
  EventDeliverySortDirectionSchema,
  EventDeliveryStatusSchema,
  type EventDeliveryStatus,
} from "../schemas";
import type { EventDeliveryFilters } from "../utils";
import { EventDeliveryFilterBar } from "./event-delivery-filter-bar";
import { EventDeliveryList } from "./event-delivery-list";
import { EventDeliverySummaryCards } from "./event-delivery-summary-cards";

const filterParsers = {
  q: parseAsString.withDefault(""),
  status: parseAsStringEnum(EventDeliveryStatusSchema.options),
  orgId: parseAsString.withDefault(""),
  orgName: parseAsString.withDefault(""),
  eventName: parseAsString,
  from: parseAsString.withDefault(""),
  to: parseAsString.withDefault(""),
  sort: parseAsStringEnum(EventDeliverySortDirectionSchema.options).withDefault("NEWEST_FIRST"),
};

export function EventDeliveryMonitorPage() {
  const [urlFilters, setUrlFilters] = useQueryStates(filterParsers, { history: "replace" });
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const filters: EventDeliveryFilters = useMemo(
    () => ({
      search: urlFilters.q || undefined,
      status: urlFilters.status ?? undefined,
      organizationId: urlFilters.orgId || undefined,
      eventName: urlFilters.eventName ?? undefined,
      createdFrom: urlFilters.from || undefined,
      createdTo: urlFilters.to || undefined,
      sort: urlFilters.sort,
    }),
    [urlFilters],
  );

  const hasActiveFilters = !!(
    filters.search ||
    filters.status ||
    filters.organizationId ||
    filters.eventName ||
    filters.createdFrom ||
    filters.createdTo
  );

  const summary = useEventDeliverySummary();
  const { eventTypes } = useEventDeliveryEventTypes();
  const {
    deliveries,
    total,
    hasNextPage,
    fetchNextPage,
    isFetchingNextPage,
    isPending,
    error,
    refetch,
  } = useEventDeliveries(filters);

  const handleChange = useCallback(
    (key: keyof typeof urlFilters, value: string | null) => {
      setUrlFilters({ [key]: value || null });
    },
    [setUrlFilters],
  );

  const handleClear = useCallback(() => {
    setUrlFilters({
      q: null,
      status: null,
      orgId: null,
      orgName: null,
      eventName: null,
      from: null,
      to: null,
    });
  }, [setUrlFilters]);

  const handleOrganizationChange = useCallback(
    (organization: { id: string; name: string } | null) => {
      setUrlFilters({ orgId: organization?.id ?? null, orgName: organization?.name ?? null });
    },
    [setUrlFilters],
  );

  const handleDateRangeChange = useCallback(
    (from: string, to: string) => {
      setUrlFilters({ from: from || null, to: to || null });
    },
    [setUrlFilters],
  );

  const handleSelectStatus = useCallback(
    (status: EventDeliveryStatus) => {
      setUrlFilters({ status: urlFilters.status === status ? null : status });
    },
    [setUrlFilters, urlFilters.status],
  );

  const handleRefresh = useCallback(() => {
    setExpandedId(null);
    void summary.refetch();
    void refetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [summary.refetch, refetch]);

  return (
    <div className="max-w-[1200px] mx-auto px-10 pt-9 pb-24">
      <div className="flex flex-wrap items-start justify-between gap-3 mb-7">
        <div>
          <h1 className="text-[28px] font-semibold tracking-tight m-0 mb-1" style={{ color: "var(--ink)" }}>
            Event Delivery Monitor
          </h1>
          <p className="text-[14px] m-0" style={{ color: "var(--ink-3)" }}>
            Inspect delivery pipeline health and diagnose handler failures.
          </p>
        </div>
        <button className="af-btn flex-shrink-0" onClick={handleRefresh}>
          <RefreshCw size={14} /> Refresh
        </button>
      </div>

      <EventDeliverySummaryCards
        summary={summary.summary}
        isLoading={summary.isLoading}
        activeStatus={filters.status}
        onSelectStatus={handleSelectStatus}
      />

      <EventDeliveryFilterBar
        values={urlFilters}
        onChange={handleChange}
        onOrganizationChange={handleOrganizationChange}
        onDateRangeChange={handleDateRangeChange}
        eventTypes={eventTypes}
        hasActiveFilters={hasActiveFilters}
        onClear={handleClear}
      />

      <p className="text-[13px] mb-3" style={{ color: "var(--ink-4)" }}>
        {total.toLocaleString()} {total === 1 ? "delivery" : "deliveries"}
      </p>

      <EventDeliveryList
        deliveries={deliveries}
        isLoading={isPending}
        error={error}
        onRetry={() => void refetch()}
        expandedId={expandedId}
        onToggleExpand={(id) => setExpandedId((current) => (current === id ? null : id))}
        hasActiveFilters={hasActiveFilters}
        hasNextPage={Boolean(hasNextPage)}
        isFetchingNextPage={isFetchingNextPage}
        onLoadMore={fetchNextPage}
      />
    </div>
  );
}
