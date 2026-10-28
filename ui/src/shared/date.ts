const mediumDateTimeFormatter = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
});

export function formatDate(value: string | Date): string {
  return mediumDateTimeFormatter.format(
    typeof value === "string" ? new Date(value) : value,
  );
}

const relativeTimeFormatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });

const RELATIVE_UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 365 * 24 * 60 * 60],
  ["month", 30 * 24 * 60 * 60],
  ["week", 7 * 24 * 60 * 60],
  ["day", 24 * 60 * 60],
  ["hour", 60 * 60],
  ["minute", 60],
];

/** How long ago a moment was, such as "2 hours ago"; under a minute reads "just now". */
export function formatRelativeTime(value: string | Date, now: Date = new Date()): string {
  const seconds = ((typeof value === "string" ? new Date(value) : value).getTime() - now.getTime()) / 1000;
  for (const [unit, size] of RELATIVE_UNITS) {
    if (Math.abs(seconds) >= size) return relativeTimeFormatter.format(Math.round(seconds / size), unit);
  }
  return "just now";
}
