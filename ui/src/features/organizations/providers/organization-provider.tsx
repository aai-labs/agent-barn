"use client";

import {
  createContext,
  type ReactNode,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
} from "react";
import { useParams, useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";

import { AuthLoadingFallback } from "@/auth/components/auth-loading-fallback";
import { useCurrentUser } from "@/auth/providers/user-context-provider";
import { useOrgStore } from "@/features/organizations/stores/org-store";
import { useOrgStoreHydrated } from "@/features/organizations/stores/use-org-store-hydrated";
import { useAllOrganizations } from "@/features/organizations/hooks/use-all-organizations";
import { api, ORGANIZATION_HEADER } from "@/shared/api";

import type { Organization } from "../schemas";

// Org-scoped query base-keys dropped on org switch so the previous org's data can't
// linger under the new org (these keys aren't org-dimensioned). Deny-list, not an
// allow-list: user/session queries (current-user-context, etc.) and global lists
// (organizations, users) must survive — evicting current-user-context would unmount the
// whole authenticated tree behind UserContextProvider's loading fallback on every switch.
const ORG_SCOPED_QUERY_KEYS = new Set([
  "agents",
  "templates",
  "tool-calls",
  "cost",
  "skills",
]);

type OrganizationContextValue = {
  organizations: Organization[];
  selectedOrganization: Organization | null;
};

const OrganizationContext = createContext<OrganizationContextValue | undefined>(
  undefined,
);

export function OrganizationProvider({ children }: { children: ReactNode }) {
  const { user, userContext } = useCurrentUser();
  const params = useParams();
  const router = useRouter();
  const hasHydrated = useOrgStoreHydrated();
  const storedOrganizationId = useOrgStore(
    (state) => state.selectedByUser[user.id],
  );
  const setOrganizationId = useOrgStore((state) => state.setOrganizationId);

  // The active org lives in the URL (`/dashboard/[orgId]/…`). Global routes (all-orgs,
  // account) have no orgId; there we fall back to the remembered/default org so the
  // switcher still has a selection and the header stays valid.
  const urlOrganizationId =
    typeof params?.orgId === "string" ? params.orgId : null;

  // Superusers aren't members of the orgs they manage, so their picker is populated
  // from the full org list rather than their memberships.
  const { organizations: allOrganizations, isLoading: isLoadingAllOrganizations } =
    useAllOrganizations({ enabled: user.isSuperuser });

  const organizations = useMemo(() => {
    if (user.isSuperuser) {
      return allOrganizations;
    }
    return (userContext.organizationUsers ?? []).map(
      (membership) => membership.organization,
    );
  }, [user.isSuperuser, allOrganizations, userContext.organizationUsers]);

  const fallbackOrganization = useMemo(
    () => organizations.find((org) => org.isDefault) ?? organizations[0] ?? null,
    [organizations],
  );

  const selectedOrganization = useMemo(() => {
    if (organizations.length === 0) {
      return null;
    }
    const byUrl = urlOrganizationId
      ? organizations.find((org) => org.id === urlOrganizationId)
      : undefined;
    if (byUrl) return byUrl;

    const byStore = storedOrganizationId
      ? organizations.find((org) => org.id === storedOrganizationId)
      : undefined;
    return byStore ?? fallbackOrganization;
  }, [organizations, urlOrganizationId, storedOrganizationId, fallbackOrganization]);

  const activeOrgId = selectedOrganization?.id ?? null;

  // Attach the active org to every API request *before* children fetch. In render (not an
  // effect) so the first child query is already scoped. Source of truth is the URL org.
  const headerOrgIdRef = useRef<string | null>(null);
  if (headerOrgIdRef.current !== activeOrgId) {
    if (activeOrgId) {
      api.setHeader(ORGANIZATION_HEADER, activeOrgId);
    } else {
      api.removeHeader(ORGANIZATION_HEADER);
    }
    headerOrgIdRef.current = activeOrgId;
  }

  // Remember the active org so /dashboard (and post-login) can redirect into it.
  useEffect(() => {
    if (activeOrgId && activeOrgId !== storedOrganizationId) {
      setOrganizationId(user.id, activeOrgId);
    }
  }, [activeOrgId, storedOrganizationId, setOrganizationId, user.id]);

  // On org switch, DROP org-scoped cache rather than merely invalidating it. Those list
  // keys aren't org-dimensioned, so invalidate would keep the previous org's data on
  // screen during the refetch — the new org's URL/header active but the old org's
  // agents/templates/costs still rendered. Removing forces a fresh load instead. Only
  // org-scoped keys are touched (see ORG_SCOPED_QUERY_KEYS); user/session and global-list
  // queries are left intact so the authenticated tree doesn't remount.
  // useLayoutEffect, not useEffect: the org-scoped route segment below remounts on
  // switch and its own queries auto-refetch (stale cache, refetchOnMount) from a
  // passive effect. Passive effects run child-before-parent, so a plain useEffect here
  // would fire after that stale-cache refetch already started — removeQueries then
  // cancels it mid-flight, its correct response gets discarded, and nothing re-triggers
  // a fetch, leaving the old org's data stuck on screen. Layout effects run before any
  // component's passive effects tree-wide, so this always evicts first.
  const queryClient = useQueryClient();
  const switchedOrgIdRef = useRef<string | null>(activeOrgId);
  useLayoutEffect(() => {
    const previousOrgId = switchedOrgIdRef.current;
    if (previousOrgId === activeOrgId) return;
    switchedOrgIdRef.current = activeOrgId;
    // Only a genuine org-to-org switch should drop caches. The initial resolution
    // (null -> org, e.g. a superuser's org list arriving asynchronously) is not a switch:
    // evicting there would wipe the just-loaded agents/templates mid-render and flash a
    // reload. Nothing stale exists before the first org is known, so skip it.
    if (previousOrgId === null || activeOrgId === null) return;
    queryClient.removeQueries({
      predicate: (query) =>
        ORG_SCOPED_QUERY_KEYS.has(query.queryKey[0] as string),
    });
  }, [activeOrgId, queryClient]);

  // A URL org the user can't reach (non-superuser, not a member; or a stale/unknown id)
  // falls back to their default org rather than 403-ing every scoped request.
  const canAccessUrlOrg =
    !urlOrganizationId ||
    organizations.some((org) => org.id === urlOrganizationId);
  useEffect(() => {
    if (!hasHydrated || isLoadingAllOrganizations) return;
    if (!canAccessUrlOrg && fallbackOrganization) {
      router.replace(`/dashboard/${fallbackOrganization.id}`);
    }
  }, [
    canAccessUrlOrg,
    fallbackOrganization,
    hasHydrated,
    isLoadingAllOrganizations,
    router,
  ]);

  if (!userContext) {
    return <AuthLoadingFallback message="Unable to load organizations." />;
  }

  if (!hasHydrated || isLoadingAllOrganizations) {
    return <AuthLoadingFallback message="Loading organizations..." />;
  }

  return (
    <OrganizationContext.Provider value={{ organizations, selectedOrganization }}>
      {children}
    </OrganizationContext.Provider>
  );
}

export function useOrganizationContext() {
  const context = useContext(OrganizationContext);
  if (!context) {
    throw new Error(
      "useOrganizationContext must be used inside OrganizationProvider",
    );
  }
  return context;
}
