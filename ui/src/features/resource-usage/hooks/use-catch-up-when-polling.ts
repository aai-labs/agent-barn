"use client";

import { useEffect, useRef } from "react";

/**
 * When polling resumes (a row scrolls back into view), refresh at once if the last answer
 * is older than one polling interval, rather than show it for up to another interval.
 */
export function useCatchUpWhenPolling(
  query: { dataUpdatedAt: number; refetch: () => unknown },
  poll: boolean,
  intervalMs: number,
) {
  // The latest answer's time, read when polling resumes; a new answer alone must not refetch.
  const latest = useRef(query);
  useEffect(() => {
    latest.current = query;
  });

  useEffect(() => {
    const { dataUpdatedAt, refetch } = latest.current;
    if (poll && dataUpdatedAt > 0 && Date.now() - dataUpdatedAt > intervalMs) void refetch();
  }, [poll, intervalMs]);
}
