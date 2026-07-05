"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import {
  PaginatedOrganizations,
  PaginatedOrganizationsSchema,
} from "../schemas";
import { organizationsKey } from "../utils";

// Upper bound for the org switcher. If a superuser ever manages more orgs than this,
// the picker should move to a searchable/paginated list.
const ALL_ORGANIZATIONS_PAGE_SIZE = 200;

/**
 * Fetches every organization (superuser-only endpoint returns all). Used to populate
 * the org switcher for superusers, who aren't members of the orgs they manage.
 */
export function useAllOrganizations({ enabled }: { enabled: boolean }) {
  const query = useQuery({
    queryKey: organizationsKey.list({ scope: { mode: "all" } }),
    queryFn: async () => {
      const response = await api.get<PaginatedOrganizations>(
        `/api/v1/organizations?page=1&page_size=${ALL_ORGANIZATIONS_PAGE_SIZE}`,
        { schema: PaginatedOrganizationsSchema },
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
