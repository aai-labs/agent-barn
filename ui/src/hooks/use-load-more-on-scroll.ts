"use client";

import { useEffect, useRef } from "react";

export function useLoadMoreOnScroll({
  hasNextPage,
  isFetchingNextPage,
  fetchNextPage,
}: {
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  fetchNextPage: () => void;
}) {
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const stateRef = useRef({ hasNextPage, isFetchingNextPage, fetchNextPage });

  useEffect(() => {
    stateRef.current = { hasNextPage, isFetchingNextPage, fetchNextPage };
  }, [fetchNextPage, hasNextPage, isFetchingNextPage]);

  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        const current = stateRef.current;
        if (entry.isIntersecting && current.hasNextPage && !current.isFetchingNextPage) {
          current.fetchNextPage();
        }
      },
      { rootMargin: "300px" },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [hasNextPage]);

  return sentinelRef;
}
