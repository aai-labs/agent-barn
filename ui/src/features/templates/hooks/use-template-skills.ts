"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import {
  PaginatedPlatformSkillsSchema,
  PlatformSkillListSchema,
  type PlatformSkill,
} from "../schemas";
import { useTemplateSkillsBasePath, type TemplateScopeRef } from "../scope";
import { templateSkillsKey } from "../utils";

const ORG_SKILLS_PAGE_SIZE = 200;

export function useTemplateSkills(scope: TemplateScopeRef, enabled = true) {
  const basePath = useTemplateSkillsBasePath(scope);
  const isPlatform = scope.kind === "platform";
  const query = useQuery({
    queryKey: templateSkillsKey(scope),
    queryFn: async (): Promise<PlatformSkill[]> => {
      if (isPlatform) {
        const response = await api.get<PlatformSkill[]>(basePath, {
          schema: PlatformSkillListSchema,
        });
        return response.data;
      }
      const response = await api.get<{ items: PlatformSkill[] }>(
        `${basePath}?page_size=${ORG_SKILLS_PAGE_SIZE}`,
        { schema: PaginatedPlatformSkillsSchema },
      );
      return response.data.items;
    },
    enabled,
  });

  return {
    skills: query.data ?? [],
    isLoading: query.isLoading,
    error: query.error,
  };
}
