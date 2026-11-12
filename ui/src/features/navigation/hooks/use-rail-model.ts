"use client";

import { usePathname } from "next/navigation";
import {
  ArrowLeft,
  ChartColumn,
  CreditCard,
  House,
  ListChecks,
  Receipt,
  Settings2,
  Target,
  Users,
} from "lucide-react";

import { useOrganizationBilling } from "@/features/billing/hooks/use-organization-billing";
import { usePlatformView } from "@/features/organizations/hooks/use-platform-view";
import { useActiveOrgRole } from "@/features/organizations/hooks/use-active-org-role";

import { PLATFORM_AREAS, isPlatformPageActive, type NavItem } from "../nav-model";

export type RailModel = {
  /** `platform` tints the rail: Platform View has a rail of its own. */
  tone: "neutral" | "platform";
  items: NavItem[];
  /**
   * The way back to the Organization from Platform View. Phones list it under More;
   * on desktop the path bar's switcher does this.
   */
  exit?: NavItem;
};

/**
 * The rail's destinations for the current route: the Organization's pages, or inside
 * Platform View Platform's own areas.
 */
export function useRailModel(): RailModel {
  const pathname = usePathname() ?? "";
  // Owners/admins (and platform admins) manage members and see org spend; plain members can't.
  const { canManage, role, selectedOrganization } = useActiveOrgRole();
  // From the view you are in, which a page outside both (your Account) keeps.
  const isPlatformView = usePlatformView();
  // Only the owner buys credit, and only where this organization can.
  const { billing } = useOrganizationBilling(selectedOrganization?.id, {
    enabled: role === "OWNER" && !isPlatformView,
  });
  const orgBase = selectedOrganization ? `/dashboard/${selectedOrganization.id}` : "/dashboard";

  if (isPlatformView) {
    return {
      tone: "platform",
      items: PLATFORM_AREAS.map((area) => ({
        key: area.key,
        label: area.label,
        href: area.pages.find((page) => page.key === area.key)?.href ?? area.pages[0].href,
        icon: area.icon,
        active: area.pages.some((page) => isPlatformPageActive(pathname, page.href)),
      })),
      exit: {
        key: "exit",
        label: selectedOrganization?.name ?? "Organizations",
        href: orgBase,
        icon: ArrowLeft,
        active: false,
      },
    };
  }

  const items: NavItem[] = [
    {
      key: "team",
      label: "Team",
      href: orgBase,
      icon: House,
      // Agent pages belong to the team; Usage lives at /agents itself.
      active: pathname === orgBase || pathname.startsWith(`${orgBase}/agents/`),
    },
    {
      key: "usage",
      label: "Usage",
      href: `${orgBase}/agents`,
      icon: ChartColumn,
      active: pathname === `${orgBase}/agents`,
    },
    // Costs and KPIs are owner/admin-only (their endpoints are gated too); hide them from members.
    ...(canManage
      ? [
          {
            key: "costs",
            label: "Costs",
            href: `${orgBase}/costs`,
            icon: Receipt,
            active: pathname.startsWith(`${orgBase}/costs`),
          },
          {
            key: "kpis",
            label: "KPIs",
            href: `${orgBase}/kpis`,
            icon: Target,
            active: pathname.startsWith(`${orgBase}/kpis`),
          },
          {
            key: "members",
            label: "Members",
            href: `${orgBase}/members`,
            icon: Users,
            active: pathname.startsWith(`${orgBase}/members`),
          },
        ]
      : []),
    // Every member may open it: the list holds only Tasks of Agents they can see. After the
    // Owner/Admin pages, so a phone's bottom bar keeps its destinations.
    {
      key: "tasks",
      label: "Tasks",
      href: `${orgBase}/tasks`,
      icon: ListChecks,
      active: pathname.startsWith(`${orgBase}/tasks`),
    },
    ...(billing?.available
      ? [
          {
            key: "billing",
            label: "Billing",
            href: `${orgBase}/billing`,
            icon: CreditCard,
            active: pathname.startsWith(`${orgBase}/billing`),
          },
        ]
      : []),
    {
      key: "settings",
      label: "Settings",
      href: `${orgBase}/settings`,
      icon: Settings2,
      active: pathname.startsWith(`${orgBase}/settings`),
    },
  ];

  return {
    tone: "neutral",
    items,
  };
}
