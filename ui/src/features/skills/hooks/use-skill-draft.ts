"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { SkillDraftSchema, type SkillDraft } from "../schemas";
import { useSkillsBasePath, type SkillScopeRef } from "../scope";
import { skillDraftKey } from "../utils";

/**
 * The skill's in-flight draft, if any. Only enabled when the caller already knows
 * a draft exists (e.g. Skill.hasDraft) — there's at most one per skill, so probing
 * this speculatively would mean treating a routine 404 as an error.
 */
export function useSkillDraft(skillId: string | null, enabled: boolean, scope: SkillScopeRef) {
  const basePath = useSkillsBasePath(scope);

  const query = useQuery({
    queryKey: skillDraftKey(skillId ?? "none", scope),
    enabled: skillId !== null && enabled,
    queryFn: async () => {
      const response = await api.get<SkillDraft>(`${basePath}/${skillId}/draft`, {
        schema: SkillDraftSchema,
      });
      return response.data;
    },
  });

  return {
    draft: query.data,
    isLoading: query.isPending,
    error: query.error,
  };
}
