"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import { OrganizationMemory, OrganizationMemorySchema } from "../schemas";

export function useOrganizationMemory() {
  const orgApiBase = useOrganizationApiBase();

  const query = useQuery({
    queryKey: ["organization-memory", orgApiBase],
    queryFn: async () => {
      const response = await api.get<OrganizationMemory>(`${orgApiBase}/memory`, {
        schema: OrganizationMemorySchema,
      });
      return response.data;
    },
  });

  return {
    memory: query.data,
    isLoading: query.isPending,
    error: query.error,
  };
}
