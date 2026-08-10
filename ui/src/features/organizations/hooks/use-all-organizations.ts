"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import {
  PaginatedPlatformOrganizations,
  PaginatedPlatformOrganizationsSchema,
} from "../schemas";
import { platformOrganizationsKey } from "../utils";

// Upper bound for the org switcher. If a platform admin ever manages more orgs than this,
// the picker should move to a searchable/paginated list.
const ALL_ORGANIZATIONS_PAGE_SIZE = 200;

/**
 * Fetches every organization (platform-admin-only endpoint returns all). Used to populate
 * the org switcher for platform admins, who aren't members of the orgs they manage.
 */
export function useAllOrganizations({ enabled }: { enabled: boolean }) {
  const query = useQuery({
    queryKey: platformOrganizationsKey.list({ scope: { mode: "all" } }),
    queryFn: async () => {
      const response = await api.get<PaginatedPlatformOrganizations>(
        `/api/v1/platform/organizations?page=1&page_size=${ALL_ORGANIZATIONS_PAGE_SIZE}`,
        { schema: PaginatedPlatformOrganizationsSchema },
      );
      return response.data;
    },
    enabled,
  });

  return {
    organizations: query.data?.items ?? [],
    isLoading: query.isLoading,
    error: query.error,
  };
}
