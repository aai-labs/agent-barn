"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import {
  PaginatedSharedCredentialsSchema,
  type PaginatedSharedCredentials,
} from "../schemas";
import { SHARED_CREDENTIALS_PAGE_SIZE, sharedCredentialsKey } from "../utils";

export type SharedCredentialsFilters = {
  search?: string;
  provider?: string;
  page?: number;
  pageSize?: number;
};

export function useSharedCredentials(filters: SharedCredentialsFilters = {}) {
  const orgApiBase = useOrganizationApiBase();
  const {
    search,
    provider,
    page = 1,
    pageSize = SHARED_CREDENTIALS_PAGE_SIZE,
  } = filters;

  const query = useQuery({
    queryKey: sharedCredentialsKey.list({ filters }),
    queryFn: async () => {
      const params = new URLSearchParams();
      params.set("page", String(page));
      params.set("page_size", String(pageSize));
      if (search) params.set("search", search);
      if (provider) params.set("provider", provider);
      const response = await api.get<PaginatedSharedCredentials>(
        `${orgApiBase}/shared-credentials?${params.toString()}`,
        { schema: PaginatedSharedCredentialsSchema },
      );
      return response.data;
    },
  });

  return {
    credentials: query.data?.items ?? [],
    total: query.data?.total ?? 0,
    page: query.data?.page ?? page,
    pageSize: query.data?.pageSize ?? pageSize,
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}
