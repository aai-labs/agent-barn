"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { EnvironmentHealthSchema, type EnvironmentHealth } from "../schemas";
import { ENVIRONMENT_HEALTH_REFETCH_MS, environmentHealthKey } from "../utils";

/** The health and capacity of the namespace the platform runs in. Platform Administrators only. */
export function useEnvironmentHealth() {
  const query = useQuery({
    queryKey: environmentHealthKey.all,
    queryFn: async () => {
      const response = await api.get<EnvironmentHealth>("/api/v1/platform/environment-health", {
        schema: EnvironmentHealthSchema,
      });
      return response.data;
    },
    refetchInterval: ENVIRONMENT_HEALTH_REFETCH_MS,
  });

  return {
    health: query.data ?? null,
    isLoadingHealth: query.isPending,
    isFetching: query.isFetching,
    error: query.error,
    refetch: query.refetch,
  };
}
