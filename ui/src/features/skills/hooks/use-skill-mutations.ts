"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import { SkillSchema, type Skill } from "../schemas";
import { skillsKey } from "../utils";

export type SkillFilePayload = {
  path: string;
  content: string;
};

export type SkillCreatePayload = {
  name: string;
  description?: string;
  files: SkillFilePayload[];
  requiredProviders?: string[];
};

export type SkillUpdatePayload = {
  skillId: string;
  name?: string;
  description?: string;
  // Omit to leave content untouched; supplying it publishes the next version.
  files?: SkillFilePayload[];
  requiredProviders?: string[];
};

export function useCreateSkill() {
  const queryClient = useQueryClient();
  const orgApiBase = useOrganizationApiBase();

  return useMutation({
    mutationFn: async ({ ...body }: SkillCreatePayload) => {
      const response = await api.post<Skill>(`${orgApiBase}/skills`, body, {
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
  const orgApiBase = useOrganizationApiBase();

  return useMutation({
    mutationFn: async ({ skillId, ...body }: SkillUpdatePayload) => {
      const response = await api.patch<Skill>(`${orgApiBase}/skills/${skillId}`, body, {
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
  const orgApiBase = useOrganizationApiBase();

  return useMutation({
    mutationFn: async (skillId: string) => {
      await api.delete(`${orgApiBase}/skills/${skillId}`);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: skillsKey.all });
    },
  });
}
