"use client";

import { createContext, type ReactNode, useContext, useMemo } from "react";

import { AuthLoadingFallback } from "@/auth/components/auth-loading-fallback";
import { useCurrentUser } from "@/auth/providers/user-context-provider";
import { useOrgStore } from "@/organizations/stores/org-store";
import { useOrgStoreHydrated } from "@/organizations/stores/use-org-store-hydrated";

import type { Organization } from "../schemas";

type OrganizationContextValue = {
  organizations: Organization[];
  selectedOrganization: Organization | null;
  setOrganization: (organization: Organization) => void;
};

const OrganizationContext = createContext<OrganizationContextValue | undefined>(
  undefined,
);

export function OrganizationProvider({ children }: { children: ReactNode }) {
  const { user, userContext } = useCurrentUser();
  const hasHydrated = useOrgStoreHydrated();
  const selectedOrganizationId = useOrgStore(
    (state) => state.selectedByUser[user.id],
  );
  const setOrganizationId = useOrgStore((state) => state.setOrganizationId);

  const organizations = useMemo(() => {
    const orgs = (userContext.organizationUsers ?? []).map(
      (membership) => membership.organization,
    );
    if (user.isSuperuser && orgs.length === 0) {
      return [];
    }
    return orgs;
  }, [user.isSuperuser, userContext.organizationUsers]);

  const selectedOrganization = useMemo(() => {
    if (organizations.length === 0) {
      return null;
    }

    if (selectedOrganizationId) {
      const fromStorage = organizations.find(
        (org) => org.id === selectedOrganizationId,
      );
      if (fromStorage) {
        return fromStorage;
      }
    }

    return organizations.find((org) => org.isDefault) ?? organizations[0];
  }, [organizations, selectedOrganizationId]);

  const setOrganization = (organization: Organization) => {
    if (organization.id === selectedOrganization?.id) {
      return;
    }

    setOrganizationId(user.id, organization.id);
  };

  if (!userContext) {
    return <AuthLoadingFallback message="Unable to load organizations." />;
  }

  if (!hasHydrated) {
    return <AuthLoadingFallback message="Loading organizations..." />;
  }

  return (
    <OrganizationContext.Provider
      value={{ organizations, selectedOrganization, setOrganization }}
    >
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
