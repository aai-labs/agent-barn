"use client";

import { usePathname } from "next/navigation";
import {
  ArrowLeft,
  ChartColumn,
  House,
  Receipt,
  Settings2,
  Shield,
  Target,
  Users,
} from "lucide-react";

import { useCurrentUser } from "@/auth/providers/user-context-provider";
import { useActiveOrgRole } from "@/features/organizations/hooks/use-active-org-role";

import { PLATFORM_AREAS, PLATFORM_BASE, isPlatformPageActive, type NavItem } from "../nav-model";
import { useNavVariant } from "../providers/nav-variant-provider";

export type RailModel = {
  /** `platform` tints the rail: D2 gives Platform View a rail of its own. */
  tone: "neutral" | "platform";
  items: NavItem[];
  /** The way into Platform View, for platform administrators outside it (D only). */
  platform?: NavItem;
  /** The way back to the Organization from D2's Platform rail. */
  exit?: NavItem;
};

/**
 * The rail's destinations for the current route. Organization pages are the same in
 * D and D2; inside Platform View, D keeps them and D2 swaps in Platform's own areas.
 */
export function useRailModel(): RailModel {
  const pathname = usePathname() ?? "";
  const { variant } = useNavVariant();
  const { user } = useCurrentUser();
  // Owners/admins (and platform admins) manage members and see org spend; plain members can't.
  const { canManage, selectedOrganization } = useActiveOrgRole();
  const isPlatformView = pathname.startsWith(PLATFORM_BASE);
  const orgBase = selectedOrganization ? `/dashboard/${selectedOrganization.id}` : "/dashboard";

  if (isPlatformView && variant === "d2") {
    return {
      tone: "platform",
      items: PLATFORM_AREAS.map((area) => ({
        key: area.key,
        label: area.label,
        href: area.pages[0].href,
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
    // D2 reaches Platform View from the context switcher in its top bar instead.
    platform: user.isPlatformAdmin && variant !== "d2"
      ? {
          key: "platform",
          label: "Platform",
          href: PLATFORM_BASE,
          icon: Shield,
          active: isPlatformView,
        }
      : undefined,
  };
}
