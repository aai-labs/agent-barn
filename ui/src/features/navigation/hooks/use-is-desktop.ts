"use client";

import { useSyncExternalStore } from "react";

// Tailwind's `lg` breakpoint, where the navigation panel and the top bar appear.
const DESKTOP_QUERY = "(min-width: 1024px)";

function subscribe(onChange: () => void) {
  const query = window.matchMedia(DESKTOP_QUERY);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

/**
 * Whether the desktop navigation is showing. For layout that cannot be switched with
 * CSS alone, such as mounting a live chat once rather than in two hidden copies.
 */
export function useIsDesktop() {
  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia(DESKTOP_QUERY).matches,
    () => false,
  );
}
