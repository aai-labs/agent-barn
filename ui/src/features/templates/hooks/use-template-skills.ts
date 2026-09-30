"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import {
  PaginatedTemplateSkillsSchema,
  TemplateSkillListSchema,
  type TemplateSkill,
} from "../schemas";
import { useTemplateSkillsBasePath, type TemplateScopeRef } from "../scope";
import { templateSkillsKey } from "../utils";

const ORG_SKILLS_PAGE_SIZE = 200;

export function useTemplateSkills(scope: TemplateScopeRef, enabled = true) {
  const basePath = useTemplateSkillsBasePath(scope);
  const isPlatform = scope.kind === "platform";
  const query = useQuery({
    queryKey: templateSkillsKey(scope),
    queryFn: async (): Promise<TemplateSkill[]> => {
      if (isPlatform) {
        const response = await api.get<TemplateSkill[]>(basePath, {
          schema: TemplateSkillListSchema,
        });
        return response.data;
      }
      const response = await api.get<{ items: TemplateSkill[] }>(
        `${basePath}?page_size=${ORG_SKILLS_PAGE_SIZE}`,
        { schema: PaginatedTemplateSkillsSchema },
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
