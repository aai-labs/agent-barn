"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { SkillDetailSchema, type SkillDetail } from "../schemas";
import { useSkillsBasePath, type SkillScopeRef } from "../scope";
import { skillDetailKey } from "../utils";

/** Fetches a skill's published files. Skipped until a skill is actually selected. */
export function useSkillFiles(skillId: string | null, scope: SkillScopeRef) {
  const basePath = useSkillsBasePath(scope);

  const query = useQuery({
    queryKey: skillDetailKey(skillId ?? "none", scope),
    enabled: skillId !== null,
    queryFn: async () => {
      const response = await api.get<SkillDetail>(`${basePath}/${skillId}/files`, {
        schema: SkillDetailSchema,
      });
      return response.data;
    },
  });

  return {
    detail: query.data ?? null,
    files: query.data?.files ?? [],
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}
