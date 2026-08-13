"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import { SkillDraftSchema, SkillSchema, type Skill, type SkillDraft } from "../schemas";
import { skillDraftKey, skillsKey } from "../utils";

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

/** Get-or-create the in-flight draft. Pass sourceVersion to seed it from an older
 * published version instead of the latest (rollback); omit to continue editing. */
export function useStartSkillDraft() {
  const queryClient = useQueryClient();
  const orgApiBase = useOrganizationApiBase();

  return useMutation({
    mutationFn: async ({ skillId, sourceVersion }: { skillId: string; sourceVersion?: number }) => {
      const query = sourceVersion === undefined ? "" : `?source_version=${sourceVersion}`;
      const response = await api.post<SkillDraft>(
        `${orgApiBase}/skills/${skillId}/draft${query}`,
        {},
        { schema: SkillDraftSchema },
      );
      return response.data;
    },
    onSuccess: (draft) => {
      queryClient.setQueryData(skillDraftKey(draft.skillId), draft);
    },
  });
}

export function useUpdateSkillDraft() {
  const queryClient = useQueryClient();
  const orgApiBase = useOrganizationApiBase();

  return useMutation({
    mutationFn: async ({ skillId, files }: { skillId: string; files: SkillFilePayload[] }) => {
      const response = await api.patch<SkillDraft>(
        `${orgApiBase}/skills/${skillId}/draft`,
        { files },
        { schema: SkillDraftSchema },
      );
      return response.data;
    },
    onSuccess: (draft) => {
      queryClient.setQueryData(skillDraftKey(draft.skillId), draft);
    },
  });
}

export function useDiscardSkillDraft() {
  const queryClient = useQueryClient();
  const orgApiBase = useOrganizationApiBase();

  return useMutation({
    mutationFn: async (skillId: string) => {
      await api.delete(`${orgApiBase}/skills/${skillId}/draft`);
    },
    onSuccess: (_data, skillId) => {
      queryClient.removeQueries({ queryKey: skillDraftKey(skillId) });
    },
  });
}

export function usePublishSkillDraft() {
  const queryClient = useQueryClient();
  const orgApiBase = useOrganizationApiBase();

  return useMutation({
    mutationFn: async (skillId: string) => {
      const response = await api.post<Skill>(
        `${orgApiBase}/skills/${skillId}/draft/publish`,
        {},
        { schema: SkillSchema },
      );
      return response.data;
    },
    onSuccess: (skill) => {
      queryClient.removeQueries({ queryKey: skillDraftKey(skill.id) });
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
