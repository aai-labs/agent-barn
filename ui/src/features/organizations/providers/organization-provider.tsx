"use client";

import {
  createContext,
  type ReactNode,
  useContext,
  useEffect,
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
import { api } from "@/shared/api";

import type { Organization } from "../schemas";

const ORGANIZATION_HEADER = "X-Organization-Id";

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

  // Refetch org-scoped data when the active org changes (but not on the initial set).
  const queryClient = useQueryClient();
  const invalidatedOrgIdRef = useRef<string | null>(activeOrgId);
  useEffect(() => {
    if (invalidatedOrgIdRef.current !== activeOrgId) {
      invalidatedOrgIdRef.current = activeOrgId;
      void queryClient.invalidateQueries();
    }
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
