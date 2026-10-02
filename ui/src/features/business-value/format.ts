import { formatSpend } from "@/features/costs/format";

const MINUTES_PER_HOUR = 60;
const SMALLEST_SHOWN_HOURS = 0.05;
const SMALLEST_SHOWN_RATIO = 0.005;
const LOW_PERCENT_EDGE = 0.5;
const HIGH_PERCENT_EDGE = 99.5;
const SECONDS_PER_MINUTE = 60;
const SECONDS_PER_HOUR = 3600;

export const SET_HOURLY_RATE = "Set an hourly rate";
export const NOT_ENOUGH_DATA = "not enough data";

export function missingFigure(rateIsSet: boolean): string {
  return rateIsSet ? NOT_ENOUGH_DATA : SET_HOURLY_RATE;
}

export function formatHours(minutes: number): string {
  const hours = minutes / MINUTES_PER_HOUR;
  if (minutes > 0 && hours < SMALLEST_SHOWN_HOURS) return "<0.1 h";
  return `${hours.toFixed(1)} h`;
}

export function formatValuePerDollar(ratio: number): string {
  if (ratio > 0 && ratio < SMALLEST_SHOWN_RATIO) return "<$0.01 per $1";
  return `${formatSpend(ratio)} per $1`;
}

export function formatRate(fraction: number): string {
  const percent = fraction * 100;
  if (percent > 0 && percent < LOW_PERCENT_EDGE) {
    return `${(Math.ceil(percent * 10) / 10).toFixed(1)}%`;
  }
  if (percent >= HIGH_PERCENT_EDGE && percent < 100) {
    return `${(Math.floor(percent * 10) / 10).toFixed(1)}%`;
  }
  return `${Math.round(percent)}%`;
}

export function formatResponseTime(seconds: number): string {
  if (seconds < 1) return "<1 s";
  if (Math.round(seconds * 10) / 10 < SECONDS_PER_MINUTE) return `${seconds.toFixed(1)} s`;
  const total = Math.round(seconds);
  if (total < SECONDS_PER_HOUR) {
    const minutes = Math.floor(total / SECONDS_PER_MINUTE);
    const rest = total % SECONDS_PER_MINUTE;
    return `${minutes}m ${String(rest).padStart(2, "0")}s`;
  }
  const hours = Math.floor(total / SECONDS_PER_HOUR);
  const minutes = Math.floor((total % SECONDS_PER_HOUR) / SECONDS_PER_MINUTE);
  return `${hours}h ${String(minutes).padStart(2, "0")}m`;
}

export function formatCount(count: number): string {
  return count.toLocaleString("en-US");
}
