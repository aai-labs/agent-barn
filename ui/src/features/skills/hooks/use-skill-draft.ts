"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import { SkillDraftSchema, type SkillDraft } from "../schemas";
import { skillDraftKey } from "../utils";

/**
 * The skill's in-flight draft, if any. Only enabled when the caller already knows
 * a draft exists (e.g. Skill.hasDraft) — there's at most one per skill, so probing
 * this speculatively would mean treating a routine 404 as an error.
 */
export function useSkillDraft(skillId: string | null, enabled: boolean) {
  const orgApiBase = useOrganizationApiBase();

  const query = useQuery({
    queryKey: skillDraftKey(skillId ?? "none"),
    enabled: skillId !== null && enabled,
    queryFn: async () => {
      const response = await api.get<SkillDraft>(`${orgApiBase}/skills/${skillId}/draft`, {
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
