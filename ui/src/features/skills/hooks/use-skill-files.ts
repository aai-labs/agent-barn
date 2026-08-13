"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import { SkillDetailSchema, type SkillDetail } from "../schemas";
import { skillsKey } from "../utils";

/** Fetches a skill's published files. Skipped until a skill is actually selected. */
export function useSkillFiles(skillId: string | null) {
  const orgApiBase = useOrganizationApiBase();

  const query = useQuery({
    queryKey: skillsKey.detail(skillId ?? "none"),
    enabled: skillId !== null,
    queryFn: async () => {
      const response = await api.get<SkillDetail>(
        `${orgApiBase}/skills/${skillId}/files`,
        { schema: SkillDetailSchema },
      );
      return response.data;
    },
  });

  return {
    detail: query.data ?? null,
    files: query.data?.files ?? [],
    isLoading: query.isPending,
    error: query.error,
  };
}
