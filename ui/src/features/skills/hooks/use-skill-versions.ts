"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import { SkillVersionSchema, type SkillVersion } from "../schemas";
import { skillVersionsKey } from "../utils";

/** A skill lineage's version history, newest first. */
export function useSkillVersions(skillId: string | null) {
  const orgApiBase = useOrganizationApiBase();

  const query = useQuery({
    queryKey: skillVersionsKey(skillId ?? "none"),
    enabled: skillId !== null,
    queryFn: async () => {
      const response = await api.get<SkillVersion[]>(`${orgApiBase}/skills/${skillId}/versions`, {
        schema: SkillVersionSchema.array(),
      });
      return response.data;
    },
  });

  return {
    versions: query.data ?? [],
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}
