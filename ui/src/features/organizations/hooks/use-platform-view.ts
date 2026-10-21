"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";
import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

const PLATFORM_BASE = "/dashboard/platform";
// Pages under /dashboard/ that belong to neither an Organization nor Platform View.
const NEUTRAL_SEGMENTS = new Set(["account"]);

type View = "platform" | "organization";

const useViewStore = create<{ lastView: View; setLastView: (view: View) => void }>()(
  persist(
    (set) => ({
      lastView: "organization",
      setLastView: (lastView) => set({ lastView }),
    }),
    // Per tab, like the view itself: another tab may be in the other one.
    { name: "dashboard-view", storage: createJSONStorage(() => sessionStorage) },
  ),
);

function viewOf(pathname: string): View | null {
  if (pathname.startsWith(PLATFORM_BASE)) return "platform";
  const segment = pathname.split("/")[2];
  if (pathname.startsWith("/dashboard/") && segment && !NEUTRAL_SEGMENTS.has(segment)) return "organization";
  return null;
}

/**
 * Whether the dashboard frame is in Platform View.
 *
 * A Platform or Organization page says so by its URL. A page that belongs to neither, such
 * as your Account, stays in the view you came from, so opening it from Platform View does
 * not put an Organization's rail and switcher around it.
 */
export function usePlatformView(): boolean {
  const pathname = usePathname() ?? "";
  const routeView = viewOf(pathname);
  const lastView = useViewStore((state) => state.lastView);
  const setLastView = useViewStore((state) => state.setLastView);

  useEffect(() => {
    if (routeView && routeView !== lastView) setLastView(routeView);
  }, [routeView, lastView, setLastView]);

  return (routeView ?? lastView) === "platform";
}
