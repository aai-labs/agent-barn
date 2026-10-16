"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronDown, ChevronLeft } from "lucide-react";

import { LogoMark } from "@/components/logo-mark";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";

import { useContextPanel } from "../hooks/use-context-panel";
import { PLATFORM_BASE } from "../nav-model";
import { PanelGroups, PanelHeader, PanelLink } from "./context-panel";

/**
 * The phone's top bar. Where the page has a navigation panel, the bar names the
 * context and the current section, and opens the panel's sections as a sheet.
 */
export function MobileTopBar() {
  const panel = useContextPanel();
  const pathname = usePathname() ?? "";
  const { selectedOrganization } = useOrganizationContext();
  const [open, setOpen] = useState(false);

  const barClass =
    "sticky top-0 z-30 flex h-14 flex-shrink-0 items-center gap-1 px-2 lg:hidden";
  const barStyle = { background: "var(--bg)", borderBottom: "1px solid var(--line)" };

  if (!panel) {
    return (
      <header className={`${barClass} px-4`} style={barStyle}>
        <LogoMark size={26} />
        <span className="ml-2 truncate text-[15px] font-semibold" style={{ color: "var(--ink)" }}>
          {pathname.startsWith(PLATFORM_BASE)
            ? "Platform admin"
            : (selectedOrganization?.name ?? "Agent Barn")}
        </span>
      </header>
    );
  }

  const active = panel.groups
    .flatMap((group) => group.items.flatMap((item) => [item, ...(item.children ?? [])]))
    .filter((item) => item.active)
    .at(-1);

  return (
    <header className={barClass} style={barStyle}>
      {panel.crumb && (
        <Link
          href={panel.crumb.href}
          aria-label={panel.crumb.label}
          className="af-hover-bg grid h-11 w-11 flex-shrink-0 place-items-center rounded-lg"
          style={{ color: "var(--ink-2)" }}
        >
          <ChevronLeft size={20} aria-hidden />
        </Link>
      )}
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetTrigger asChild>
          <button
            type="button"
            className="af-hover-bg flex min-h-11 min-w-0 flex-1 items-center gap-1.5 rounded-lg px-2 text-left text-[15px]"
            style={{ color: "var(--ink)" }}
          >
            <span className="truncate font-semibold">{panel.title}</span>
            {active && (
              <>
                <span aria-hidden style={{ color: "var(--ink-5)" }}>
                  /
                </span>
                <span className="truncate" style={{ color: "var(--ink-2)" }}>
                  {active.label}
                </span>
              </>
            )}
            <ChevronDown size={16} aria-hidden className="ml-auto flex-shrink-0" style={{ color: "var(--ink-4)" }} />
          </button>
        </SheetTrigger>
        <SheetContent side="bottom" className="max-h-[85vh] gap-0 overflow-y-auto rounded-t-[20px] px-3 pb-6 pt-5">
          <SheetHeader className="sr-only">
            <SheetTitle>{panel.title} sections</SheetTitle>
          </SheetHeader>
          <PanelHeader panel={panel} />
          <nav aria-label={panel.title} className="[&_a]:min-h-11">
            <PanelGroups panel={panel} onNavigate={() => setOpen(false)} />
            {panel.footer && (
              <div className="mt-3 pt-2" style={{ borderTop: "1px solid var(--line)" }}>
                <PanelLink item={panel.footer} tone={panel.tone} trailing onNavigate={() => setOpen(false)} />
              </div>
            )}
          </nav>
        </SheetContent>
      </Sheet>
    </header>
  );
}
