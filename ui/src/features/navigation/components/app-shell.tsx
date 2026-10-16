"use client";

import { Suspense } from "react";
import type { ReactNode } from "react";

import { LlmBudgetBanner } from "@/features/organizations/components/llm-budget-banner";

import { ContextPanel } from "./context-panel";
import { MobileBottomBar } from "./mobile-bottom-bar";
import { MobileTopBar } from "./mobile-top-bar";
import { NavRail } from "./nav-rail";
import { PathBar } from "./path-bar";

/**
 * The dashboard frame. On desktop: the rail down the left edge, the path bar along the
 * top, and below it the navigation panel beside the page. On phones the rail becomes a
 * bottom bar and the panel a section sheet opened from the top bar.
 */
export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen lg:flex" style={{ background: "var(--bg)" }}>
      <NavRail />
      <div className="flex min-w-0 flex-1 flex-col">
        {/* The path bar, the panel and the phone bar read the URL's query, which needs a
            boundary. */}
        <Suspense fallback={null}>
          <PathBar />
        </Suspense>
        <div className="flex-1 lg:flex">
          <Suspense fallback={null}>
            <ContextPanel />
          </Suspense>
          <div className="flex min-w-0 flex-1 flex-col pb-[calc(60px+env(safe-area-inset-bottom))] lg:pb-0">
            <Suspense fallback={null}>
              <MobileTopBar />
            </Suspense>
            {/* Exhausted only — the approaching-limit warning lives on the Costs page,
                where someone is already thinking about spend. */}
            <LlmBudgetBanner show="exhausted" />
            <main className="flex-1">{children}</main>
          </div>
        </div>
      </div>
      <MobileBottomBar />
    </div>
  );
}
