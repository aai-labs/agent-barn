"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { SkillSchema, type Skill } from "../schemas";
import { skillsKey } from "../utils";

export type SkillCreatePayload = {
  name: string;
  zipContent: string;
  requiredProviders?: string[];
};

export type SkillUpdatePayload = {
  skillId: string;
  name?: string;
  zipContent?: string;
  requiredProviders?: string[];
};

export function useCreateSkill() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ ...body }: SkillCreatePayload) => {
      const response = await api.post<Skill>("/api/v1/skills", body, {
        schema: SkillSchema,
      });
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: skillsKey.all });
    },
  });
}

export function useUpdateSkill() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ skillId, ...body }: SkillUpdatePayload) => {
      const response = await api.patch<Skill>(`/api/v1/skills/${skillId}`, body, {
        schema: SkillSchema,
      });
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: skillsKey.all });
    },
  });
}

export function useDeleteSkill() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (skillId: string) => {
      await api.delete(`/api/v1/skills/${skillId}`);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: skillsKey.all });
    },
  });
}