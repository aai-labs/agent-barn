"use client";

import Link from "next/link";

import { LogoMark } from "@/components/logo-mark";

import { useRailModel } from "../hooks/use-rail-model";
import { PLATFORM_RAIL_BACKGROUND, RAIL_BACKGROUND, type NavItem } from "../nav-model";

/**
 * The dark rail down the left edge on desktop: where in the product you are. It lists
 * the Organization's pages, or in Platform View Platform's own areas on an indigo
 * rail, and never an Agent's or a page's own sections; those belong to the panel
 * beside it. Switching Organization and the account menu live in the path bar.
 */
export function NavRail() {
  const rail = useRailModel();

  return (
    <nav
      aria-label="Main"
      className="sticky top-0 z-20 hidden h-screen w-[76px] flex-shrink-0 flex-col items-center gap-1 overflow-y-auto py-3.5 lg:flex"
      style={{ background: rail.tone === "platform" ? PLATFORM_RAIL_BACKGROUND : RAIL_BACKGROUND }}
    >
      <Link href="/dashboard" aria-label="Agent Barn home" className="mb-4 rounded-lg">
        <LogoMark size={32} />
      </Link>
      {rail.items.map((item) => (
        <RailLink key={item.key} item={item} tone={rail.tone} />
      ))}
    </nav>
  );
}

function RailLink({ item, tone }: { item: NavItem; tone: "neutral" | "platform" }) {
  const Icon = item.icon;
  const idle = tone === "platform" ? "text-[#b9b3f0]" : "text-[#a8a296]";
  const state = item.active ? "bg-white/12 text-white" : `${idle} hover:bg-white/6 hover:text-white`;

  return (
    <Link
      href={item.href}
      aria-current={item.active ? "page" : undefined}
      title={item.label}
      className={`flex w-[64px] flex-col items-center gap-[3px] rounded-xl px-1 pb-1.5 pt-2 text-center text-[10.5px] font-medium leading-tight transition-colors ${state}`}
    >
      <Icon size={19} aria-hidden />
      <span className="max-w-full truncate">{item.label}</span>
    </Link>
  );
}
