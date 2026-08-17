import type { Granularity } from "./schemas";

/**
 * Label a bucket at the resolution it was measured.
 *
 * Buckets are UTC instants, so they are rendered in UTC too — showing an
 * hourly bucket in local time would slide it off the boundary the server
 * actually grouped on.
 */
export function formatBucket(iso: string, granularity: Granularity): string {
  const d = new Date(iso);
  switch (granularity) {
    case "minute":
      return d.toLocaleTimeString("en-US", {
        hour: "2-digit",
        minute: "2-digit",
        timeZone: "UTC",
      });
    case "hour":
      return d.toLocaleTimeString("en-US", {
        hour: "numeric",
        timeZone: "UTC",
      });
    case "week":
    case "day":
      return d.toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        timeZone: "UTC",
      });
  }
}

/** Fuller label for tooltips, where the day matters even in an hourly view. */
export function formatBucketLong(iso: string, granularity: Granularity): string {
  const d = new Date(iso);
  if (granularity === "minute") {
    return d.toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      timeZone: "UTC",
    });
  }
  if (granularity === "hour") {
    return d.toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      hour: "numeric",
      timeZone: "UTC",
    });
  }
  const label = d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
  return granularity === "week" ? `Week of ${label}` : label;
}

const BUCKET_NOUN: Record<Granularity, string> = {
  minute: "minute",
  hour: "hour",
  day: "day",
  week: "week",
};

/** "Messages per hour" — the heading has to follow the resolution it renders. */
export function perBucketLabel(prefix: string, granularity: Granularity): string {
  return `${prefix} per ${BUCKET_NOUN[granularity]}`;
}

/** "that hour" — names the actual unit rather than leaking "bucket" into copy. */
export function withinLabel(granularity: Granularity): string {
  return `that ${BUCKET_NOUN[granularity]}`;
}
