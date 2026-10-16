"use client";

import { Suspense } from "react";
import type { ReactNode } from "react";

import { TopNav } from "@/components/top-nav";
import { LlmBudgetBanner } from "@/features/organizations/components/llm-budget-banner";

import { useNavVariant } from "../providers/nav-variant-provider";
import { ContextPanel } from "./context-panel";
import { DrillMobileBar, DrillSidebar } from "./drill-sidebar";
import { MobileBottomBar } from "./mobile-bottom-bar";
import { MobileTopBar } from "./mobile-top-bar";
import { NavRail } from "./nav-rail";
import { PathBar } from "./path-bar";

/**
 * The dashboard frame for the selected navigation preview: the shipped top bar; C's
 * single drill-in sidebar (a drawer on phones); or the rail with its navigation panel
 * (a bottom bar and a section sheet on phones), which in D2 also has a path bar along
 * the top on desktop.
 */
export function AppShell({ children, onHire }: { children: ReactNode; onHire: () => void }) {
  const { variant } = useNavVariant();

  if (variant === "current") {
    return (
      <div className="min-h-screen flex flex-col" style={{ background: "var(--bg)" }}>
        <TopNav onHire={onHire} />
        {/* Exhausted only — the approaching-limit warning lives on the Costs page,
            where someone is already thinking about spend. */}
        <LlmBudgetBanner show="exhausted" />
        <main className="flex-1">{children}</main>
      </div>
    );
  }

  if (variant === "c") {
    return (
      <div className="min-h-screen lg:flex" style={{ background: "var(--bg)" }}>
        {/* The sidebar and the phone bar read the URL's query, which needs a boundary. */}
        <Suspense fallback={null}>
          <DrillSidebar />
        </Suspense>
        <div className="flex min-w-0 flex-1 flex-col">
          <Suspense fallback={null}>
            <DrillMobileBar />
          </Suspense>
          <LlmBudgetBanner show="exhausted" />
          <main className="flex-1">{children}</main>
        </div>
      </div>
    );
  }

  if (variant === "d2") {
    // The top bar spans the panel and the page, so the panel starts below it.
    return (
      <div className="min-h-screen lg:flex" style={{ background: "var(--bg)" }}>
        <NavRail />
        <div className="flex min-w-0 flex-1 flex-col">
          <Suspense fallback={null}>
            <PathBar />
          </Suspense>
          <div className="flex-1 lg:flex">
            <Suspense fallback={null}>
              <ContextPanel belowTopBar />
            </Suspense>
            <div className="flex min-w-0 flex-1 flex-col pb-[calc(60px+env(safe-area-inset-bottom))] lg:pb-0">
              <Suspense fallback={null}>
                <MobileTopBar />
              </Suspense>
              <LlmBudgetBanner show="exhausted" />
              <main className="flex-1">{children}</main>
            </div>
          </div>
        </div>
        <MobileBottomBar />
      </div>
    );
  }

  return (
    <div className="min-h-screen lg:flex" style={{ background: "var(--bg)" }}>
      <NavRail />
      {/* The panel and the phone bar read the URL's query, which needs a boundary. */}
      <Suspense fallback={null}>
        <ContextPanel />
      </Suspense>
      <div className="flex min-w-0 flex-1 flex-col pb-[calc(60px+env(safe-area-inset-bottom))] lg:pb-0">
        <Suspense fallback={null}>
          <MobileTopBar />
        </Suspense>
        <LlmBudgetBanner show="exhausted" />
        <main className="flex-1">{children}</main>
      </div>
      <MobileBottomBar />
    </div>
  );
}
