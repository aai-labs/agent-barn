"use client";

import { DateRangePicker } from "@/components/date-range-picker";

import { earliestUsageDay, USAGE_RETENTION_DAYS, type UsageDates } from "../utils";

interface UsageDatePickerProps {
  dates: UsageDates;
  onChange: (from: string, to: string) => void;
  /** Names the window the page reads while no days are picked. */
  placeholder: string;
}

/** Days for a resource usage page, no further back than Prometheus keeps. */
export function UsageDatePicker({ dates, onChange, placeholder }: UsageDatePickerProps) {
  return (
    <DateRangePicker
      from={dates.from}
      to={dates.to}
      onChange={onChange}
      placeholder={placeholder}
      ariaLabel="Time range"
      minDate={earliestUsageDay()}
      maxDate={new Date()}
      maxRangeDays={USAGE_RETENTION_DAYS}
      className="af-input !h-auto"
    />
  );
}
