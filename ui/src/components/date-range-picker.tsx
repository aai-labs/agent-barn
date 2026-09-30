"use client";

import { format } from "date-fns";
import { CalendarIcon } from "lucide-react";
import { useState } from "react";
import type { DateRange } from "react-day-picker";

import { Calendar } from "@/components/ui/calendar";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

interface DateRangePickerProps {
  /** ISO datetime strings, or "" when unset. */
  from: string;
  to: string;
  onChange: (from: string, to: string) => void;
  /** Shown on the trigger while nothing is selected. */
  placeholder?: string;
  /** Trigger width; omit to size to content. */
  width?: string;
  /** Trigger classes, so the control can match the surrounding toolbar. */
  className?: string;
  /** Optional. Leave unset so the trigger is named by its current value. */
  ariaLabel?: string;
  /** Maximum number of inclusive calendar days a selected range may span. */
  maxRangeDays?: number;
}

function toDateRange(from: string, to: string): DateRange | undefined {
  if (!from && !to) return undefined;
  return {
    from: from ? new Date(from) : undefined,
    to: to ? new Date(to) : undefined,
  };
}

/**
 * Range picker over Popover + Calendar.
 *
 * Bounds come back as local start-of-day and end-of-day so a picked day is
 * covered end to end, which is what every caller here wants — the API treats
 * both bounds as inclusive.
 */
export function DateRangePicker({
  from,
  to,
  onChange,
  placeholder = "Date range",
  width = "15rem",
  className = "af-input",
  ariaLabel,
  maxRangeDays,
}: DateRangePickerProps) {
  const range = toDateRange(from, to);
  const [rangeError, setRangeError] = useState<string | null>(null);

  const label = range?.from
    ? range.to
      ? `${format(range.from, "MMM d, yyyy")} – ${format(range.to, "MMM d, yyyy")}`
      : format(range.from, "MMM d, yyyy")
    : placeholder;

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={ariaLabel}
          className={`${className} flex items-center gap-2`}
          style={width ? { width } : undefined}
        >
          <CalendarIcon
            size={13}
            style={{ color: "var(--ink-4)", flexShrink: 0 }}
          />
          <span className="truncate">{label}</span>
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-auto p-0" align="start">
        <Calendar
          mode="range"
          selected={range}
          defaultMonth={range?.from}
          numberOfMonths={2}
          disabled={
            maxRangeDays && range?.from && !range.to
              ? (date) => calendarDayDistance(range.from!, date) + 1 > maxRangeDays
              : undefined
          }
          onSelect={(next) => {
            if (
              maxRangeDays &&
              next?.from &&
              next?.to &&
              calendarDayDistance(next.from, next.to) + 1 > maxRangeDays
            ) {
              setRangeError(`Choose a range of ${maxRangeDays} days or less.`);
              return;
            }
            setRangeError(null);
            onChange(
              next?.from ? startOfDayIso(next.from) : "",
              next?.to ? endOfDayIso(next.to) : "",
            );
          }}
        />
        {(rangeError || maxRangeDays) && (
          <p
            className="border-t px-3 py-2 text-xs"
            role={rangeError ? "alert" : undefined}
            style={{ borderColor: "var(--line)", color: rangeError ? "var(--err)" : "var(--ink-4)" }}
          >
            {rangeError ?? `Maximum range: ${maxRangeDays} days.`}
          </p>
        )}
        {(from || to) && (
          <div className="p-2 border-t" style={{ borderColor: "var(--line)" }}>
            <button
              type="button"
              className="af-btn w-full"
              onClick={() => onChange("", "")}
            >
              Clear dates
            </button>
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}

function startOfDayIso(date: Date): string {
  const start = new Date(date);
  start.setHours(0, 0, 0, 0);
  return start.toISOString();
}

function endOfDayIso(date: Date): string {
  const end = new Date(date);
  end.setHours(23, 59, 59, 999);
  return end.toISOString();
}

function calendarDayDistance(left: Date, right: Date): number {
  const leftDay = new Date(left.getFullYear(), left.getMonth(), left.getDate()).getTime();
  const rightDay = new Date(right.getFullYear(), right.getMonth(), right.getDate()).getTime();
  return Math.round(Math.abs(leftDay - rightDay) / (24 * 60 * 60 * 1000));
}
