"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { PlatformSkillListSchema, type PlatformSkill } from "../schemas";
import { useTemplateSkillsBasePath, type TemplateScopeRef } from "../scope";
import { templateSkillsKey } from "../utils";

export function useTemplateSkills(scope: TemplateScopeRef, enabled = true) {
  const basePath = useTemplateSkillsBasePath(scope);
  const query = useQuery({
    queryKey: templateSkillsKey(scope),
    queryFn: async () => {
      const response = await api.get<PlatformSkill[]>(basePath, {
        schema: PlatformSkillListSchema,
      });
      return response.data;
    },
    enabled,
  });

  return {
    skills: query.data ?? [],
    isLoading: query.isPending,
    error: query.error,
  };
}
