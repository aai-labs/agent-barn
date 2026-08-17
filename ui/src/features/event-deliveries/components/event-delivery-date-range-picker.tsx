"use client";

import { DateRangePicker } from "@/components/date-range-picker";

interface EventDeliveryDateRangePickerProps {
  /** ISO datetime strings, or "" when unset. */
  from: string;
  to: string;
  onChange: (from: string, to: string) => void;
}

/** Thin wrapper so this feature's call sites keep their own naming. */
export function EventDeliveryDateRangePicker(
  props: EventDeliveryDateRangePickerProps,
) {
  return <DateRangePicker {...props} placeholder="Created date range" />;
}
