"use client";

import { useCallback, useTransition } from "react";
import { usePathname, useRouter } from "next/navigation";

import { useCurrentUser } from "@/auth/providers/user-context-provider";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";

import type { Organization } from "../schemas";
import { usePlatformView } from "./use-platform-view";

// Segments directly under /dashboard/ that are NOT an org id (global admin / personal).
const GLOBAL_DASHBOARD_SEGMENTS = new Set(["account", "platform"]);

/**
 * Where switching to another Organization lands, from the page you are on.
 *
 * The same page under the new Organization where that page exists there. A page about one
 * of the old Organization's things (an Agent and its sub-pages, a skill, a template) names
 * something the new Organization does not have, so it lands on the list it came from
 * instead: the team for an Agent, the settings tab for a skill or template. From a page
 * outside any Organization it lands on the new Organization's home.
 */
export function organizationSwitchTarget(pathname: string, orgId: string): string {
  const parts = pathname.split("/"); // ["", "dashboard", <seg>, ...rest]
  const isOrgScopedRoute = parts[1] === "dashboard" && !!parts[2] && !GLOBAL_DASHBOARD_SEGMENTS.has(parts[2]);
  const home = `/dashboard/${orgId}`;
  if (!isOrgScopedRoute) return home;

  const [section, sub, id] = parts.slice(3);
  if (section === "agents" && sub) return home;
  if (section === "settings" && (sub === "skills" || sub === "templates") && id) {
    return `${home}/settings?tab=${sub}`;
  }
  parts[2] = orgId;
  return parts.join("/");
}

const PLATFORM_HOME = "/dashboard/platform";

/**
 * Moving between Organizations and Platform View, for every switcher that offers it.
 *
 * A switcher is a menu, not a link, so Next.js never prefetches its targets on its own and
 * a switch would wait on the server before anything changed on screen. Call
 * `prefetchSwitchTargets` when the switcher shows (and again when it opens) so the new
 * page's loading state appears the moment a target is picked. `isSwitching` covers a pick
 * that lands before that prefetch finishes.
 */
export function useOrganizationSwitch() {
  const { organizations, selectedOrganization } = useOrganizationContext();
  const { user } = useCurrentUser();
  const router = useRouter();
  const pathname = usePathname() ?? "";
  const isPlatformView = usePlatformView();
  // Mirrors the API: a self-signed-up user stays on their trial (even after deleting
  // it) until a platform admin ends it, and nobody owning a running trial creates more.
  const onTrial =
    (Boolean(user.signedUpAt) && !user.trialEndedAt) ||
    (user.organizationUsers ?? []).some(
      (membership) => membership.role === "OWNER" && membership.organization.isTrial,
    );

  const [isSwitching, startTransition] = useTransition();
  const currentOrgId = isPlatformView ? null : (selectedOrganization?.id ?? null);
  const inPlatform = pathname.startsWith(PLATFORM_HOME);

  const prefetchSwitchTargets = useCallback(() => {
    for (const org of organizations) {
      if (org.id !== currentOrgId) router.prefetch(organizationSwitchTarget(pathname, org.id));
    }
    if (user.isPlatformAdmin && !inPlatform) router.prefetch(PLATFORM_HOME);
  }, [organizations, currentOrgId, pathname, inPlatform, user.isPlatformAdmin, router]);

  const selectOrganization = (org: Organization) => {
    if (org.id === currentOrgId) return;
    startTransition(() => router.push(organizationSwitchTarget(pathname, org.id)));
  };

  const selectPlatform = () => {
    if (!inPlatform) startTransition(() => router.push(PLATFORM_HOME));
  };

  return {
    organizations,
    selectedOrganization,
    isPlatformView,
    isPlatformAdmin: user.isPlatformAdmin,
    canCreateOrganization: !onTrial,
    selectOrganization,
    selectPlatform,
    prefetchSwitchTargets,
    isSwitching,
  };
}
