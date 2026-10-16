"use client";

import Link from "next/link";

import { LogoMark } from "@/components/logo-mark";

import { useRailModel } from "../hooks/use-rail-model";
import { useNavVariant } from "../providers/nav-variant-provider";
import { PLATFORM_RAIL_BACKGROUND, RAIL_BACKGROUND, type NavItem } from "../nav-model";
import { ContextSwitcher } from "./context-switcher";
import { UserMenu } from "./user-menu";

/**
 * The dark rail down the left edge on desktop: where in the product you are. It stays
 * the same across a context (an Organization, or D2's Platform View) and never holds an
 * Agent's or a page's own sections; those belong to the panel beside it.
 */
export function NavRail() {
  const rail = useRailModel();
  // D2's top bar carries the context switcher and the account menu.
  const { variant } = useNavVariant();
  const hasTopBar = variant === "d2";

  return (
    <nav
      aria-label="Main"
      className="sticky top-0 z-20 hidden h-screen w-[76px] flex-shrink-0 flex-col items-center gap-1 overflow-y-auto py-3.5 lg:flex"
      style={{ background: rail.tone === "platform" ? PLATFORM_RAIL_BACKGROUND : RAIL_BACKGROUND }}
    >
      <Link href="/dashboard" aria-label="Agent Barn home" className="mb-2.5 rounded-lg">
        <LogoMark size={32} background="#fbfaf8" foreground={RAIL_BACKGROUND} />
      </Link>
      {hasTopBar ? (
        <div className="mb-1.5" />
      ) : (
        <div className="mb-3">
          <ContextSwitcher />
        </div>
      )}
      {rail.items.map((item) => (
        <RailLink key={item.key} item={item} tone={rail.tone} />
      ))}
      <div className="flex-1" />
      {rail.platform && <RailLink item={rail.platform} tone={rail.tone} accent />}
      {/* D2's top-bar switcher leads back to the Organization; phones keep this under More. */}
      {rail.exit && !hasTopBar && <RailLink item={rail.exit} tone={rail.tone} />}
      {!hasTopBar && (
        <div className="mt-2.5">
          <UserMenu />
        </div>
      )}
    </nav>
  );
}

function RailLink({
  item,
  tone,
  accent = false,
}: {
  item: NavItem;
  tone: "neutral" | "platform";
  /** Platform's own entry turns indigo while it is the current context. */
  accent?: boolean;
}) {
  const Icon = item.icon;
  const idle = tone === "platform" ? "text-[#b9b3f0]" : "text-[#a8a296]";
  const state = item.active
    ? accent
      ? "bg-[#4338ca] text-white"
      : "bg-white/12 text-white"
    : `${idle} hover:bg-white/6 hover:text-white`;

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
