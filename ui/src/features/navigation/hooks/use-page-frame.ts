"use client";

import { usePathname } from "next/navigation";

import { parseAgentRoute } from "../nav-model";
import { useContextPanel } from "./use-context-panel";

/**
 * How the dashboard frames the page beside the navigation. Every dashboard page gets the
 * same frame from the shell (`.af-page`: the canonical width and margins), so no page sets
 * its own. The few that need more of the screen on desktop are named here, in one place:
 *
 * - `page`: the canonical width and margins.
 * - `fill`: edge to edge below the path bar, for a panel that is the whole page (an
 *   Agent's Chat and Conversations).
 * - `tall`: the canonical width and margins, grown to the window's height (an Agent's live
 *   Logs).
 * - `bare`: no frame, for a screen that centres itself in the window (`/dashboard` itself,
 *   which tells someone with no Organization so, or waits for their session).
 *
 * The Agent's section is read from the navigation panel's selection, which applies the
 * same Permissions the Agent page does, so the frame and the page cannot disagree about
 * which section is showing.
 */
export type PageFrame = "page" | "fill" | "tall" | "bare";

export function usePageFrame(): PageFrame {
  const pathname = usePathname() ?? "";
  const panel = useContextPanel();
  if (pathname === "/dashboard") return "bare";
  const agentRoute = parseAgentRoute(pathname);
  if (!agentRoute || agentRoute.rest || !panel?.agent) return "page";

  const section = panel.groups.flatMap((group) => group.items).find((item) => item.active)?.key;
  if (section === "chat" || section === "conversations") return "fill";
  if (section === "logs") return "tall";
  return "page";
}

/** The `<main>` classes for a frame. The `fill` and `tall` variants apply on desktop only. */
export const PAGE_FRAME_CLASS: Record<PageFrame, string> = {
  page: "af-page",
  fill: "af-page af-page-fill",
  tall: "af-page af-page-tall",
  bare: "",
};
