"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { PlatformSkillListSchema, type PlatformSkill } from "../schemas";
import { platformTemplatesKey } from "../utils";

export function usePlatformSkills(enabled = true) {
  const query = useQuery({
    queryKey: [...platformTemplatesKey.all, "skills"],
    queryFn: async () => {
      const response = await api.get<PlatformSkill[]>("/api/v1/platform/skills", {
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
