"use client";

import { Suspense } from "react";
import type { ReactNode } from "react";

import { LlmBudgetBanner } from "@/features/organizations/components/llm-budget-banner";
import { cn } from "@/lib/utils";

import { PAGE_FRAME_CLASS, usePageFrame, type PageFrame } from "../hooks/use-page-frame";
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
          {/* The frame reads the URL's query too; until it can, the page has the usual one. */}
          <Suspense fallback={<PageColumn frame="page">{children}</PageColumn>}>
            <FramedPageColumn>{children}</FramedPageColumn>
          </Suspense>
        </div>
      </div>
      <MobileBottomBar />
    </div>
  );
}

function FramedPageColumn({ children }: { children: ReactNode }) {
  return <PageColumn frame={usePageFrame()}>{children}</PageColumn>;
}

/**
 * The page beside the navigation, in its frame (`usePageFrame`): every page's width and
 * margins come from here, never from the page. A frame that grows to the window's height
 * holds this column to it on desktop, so the page inside can fill it.
 */
function PageColumn({ frame, children }: { frame: PageFrame; children: ReactNode }) {
  return (
    <div
      className={cn(
        "flex min-w-0 flex-1 flex-col pb-[calc(60px+env(safe-area-inset-bottom))] lg:pb-0",
        (frame === "fill" || frame === "tall") && "lg:h-[calc(100vh-3.5rem)]",
      )}
    >
      <Suspense fallback={null}>
        <MobileTopBar />
      </Suspense>
      {/* Exhausted only — the approaching-limit warning lives on the Costs page,
          where someone is already thinking about spend. */}
      <LlmBudgetBanner show="exhausted" />
      {/* w-full: .af-page centres itself with auto margins, which in a flex column would
          otherwise shrink it to its content. */}
      <main className={cn("w-full flex-1", PAGE_FRAME_CLASS[frame])}>{children}</main>
    </div>
  );
}
