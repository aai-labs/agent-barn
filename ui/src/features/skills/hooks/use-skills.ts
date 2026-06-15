"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { SkillsListSchema, type Skill } from "../schemas";
import { skillsKey } from "../utils";

export function useSkills() {
  const query = useQuery({
    queryKey: skillsKey.list(),
    queryFn: async () => {
      const response = await api.get<Skill[]>("/api/v1/skills", {
        schema: SkillsListSchema,
      });
      return response.data;
    },
  });

  return {
    skills: query.data ?? [],
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}