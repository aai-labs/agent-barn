"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { SkillVersionSchema, type SkillVersion } from "../schemas";
import { useSkillsBasePath, type SkillScopeRef } from "../scope";
import { skillVersionsKey } from "../utils";

/** A skill lineage's version history, newest first.
 *
 * `enabled` defaults to true (the detail page's history tab wants it eagerly),
 * but callers rendering many rows at once — e.g. one version-pin selector per
 * assigned skill — should pass `false` until the control is actually opened, so
 * mounting the list doesn't fire one request per row. */
export function useSkillVersions(skillId: string | null, scope: SkillScopeRef, enabled = true) {
  const basePath = useSkillsBasePath(scope);

  const query = useQuery({
    queryKey: skillVersionsKey(skillId ?? "none", scope),
    enabled: skillId !== null && enabled,
    queryFn: async () => {
      const response = await api.get<SkillVersion[]>(`${basePath}/${skillId}/versions`, {
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
