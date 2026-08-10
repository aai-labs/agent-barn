"use client";

import { SearchInput } from "@/components/search-input";

import { EVENT_DELIVERY_STATUS_LABELS } from "../constants";
import { EventDeliveryStatusSchema, type SupportedEventType } from "../schemas";
import { EventDeliveryDateRangePicker } from "./event-delivery-date-range-picker";
import { EventDeliveryOrganizationCombobox } from "./event-delivery-organization-combobox";

const STATUS_OPTIONS = EventDeliveryStatusSchema.options;

export interface EventDeliveryFilterBarValues {
  q: string;
  status: string | null;
  orgId: string;
  orgName: string;
  eventName: string | null;
  from: string;
  to: string;
  sort: "NEWEST_FIRST" | "OLDEST_FIRST";
}

interface EventDeliveryFilterBarProps {
  values: EventDeliveryFilterBarValues;
  onChange: (key: keyof EventDeliveryFilterBarValues, value: string | null) => void;
  onOrganizationChange: (organization: { id: string; name: string } | null) => void;
  onDateRangeChange: (from: string, to: string) => void;
  eventTypes: SupportedEventType[];
  hasActiveFilters: boolean;
  onClear: () => void;
}

export function EventDeliveryFilterBar({
  values,
  onChange,
  onOrganizationChange,
  onDateRangeChange,
  eventTypes,
  hasActiveFilters,
  onClear,
}: EventDeliveryFilterBarProps) {
  return (
    <div className="flex flex-wrap items-center gap-2.5 mb-4">
      <SearchInput
        initialValue={values.q}
        onSearch={(value) => onChange("q", value)}
        placeholder="Search by Delivery ID, Event ID, org, event, or handler"
        className="min-w-72 flex-1"
      />

      <select
        className="af-input"
        style={{ width: "10.5rem" }}
        value={values.status ?? ""}
        onChange={(e) => onChange("status", e.target.value || null)}
      >
        <option value="">All statuses</option>
        {STATUS_OPTIONS.map((status) => (
          <option key={status} value={status}>
            {EVENT_DELIVERY_STATUS_LABELS[status]}
          </option>
        ))}
      </select>

      <select
        className="af-input"
        style={{ width: "12rem" }}
        value={values.eventName ?? ""}
        onChange={(e) => onChange("eventName", e.target.value || null)}
      >
        <option value="">All events</option>
        {eventTypes.map((eventType) => (
          <option key={eventType.eventName} value={eventType.eventName}>
            {eventType.eventName}
          </option>
        ))}
      </select>

      <EventDeliveryOrganizationCombobox
        organizationId={values.orgId || null}
        organizationName={values.orgName || null}
        onChange={onOrganizationChange}
      />

      <EventDeliveryDateRangePicker from={values.from} to={values.to} onChange={onDateRangeChange} />

      <select
        className="af-input"
        style={{ width: "9.5rem" }}
        value={values.sort}
        onChange={(e) => onChange("sort", e.target.value as "NEWEST_FIRST" | "OLDEST_FIRST")}
      >
        <option value="NEWEST_FIRST">Newest first</option>
        <option value="OLDEST_FIRST">Oldest first</option>
      </select>

      {hasActiveFilters && (
        <button className="af-btn" onClick={onClear}>
          Clear filters
        </button>
      )}
    </div>
  );
}
