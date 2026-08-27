"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { SkillDetailSchema, SkillDraftSchema, SkillSchema, type Skill, type SkillDetail, type SkillDraft } from "../schemas";
import { useSkillsBasePath, type SkillScopeRef } from "../scope";
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
};

/** Create a new lineage in `scope` with an initial unpublished draft. Parsed with the
 * lineage-level schema even though Platform/Agent responses also include the
 * file/assignment fields Organization's response omits — the extra fields are
 * simply ignored, so one schema covers all three scopes' create response. */
export function useCreateSkill(scope: SkillScopeRef) {
  const queryClient = useQueryClient();
  const basePath = useSkillsBasePath(scope);

  return useMutation({
    mutationFn: async (body: SkillCreatePayload) => {
      const response = await api.post<Skill>(basePath, body, { schema: SkillSchema });
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: skillsKey.all });
    },
  });
}

/** Fork a visible Platform (or, from Agent scope, also Organization) Skill into
 * `scope`, seeded from its latest version with an in-flight draft ready to edit.
 * Not applicable to Platform scope — nothing sits above it to fork from. Accepts
 * the full scope union (rather than excluding "platform" at the type level) only
 * so callers can instantiate it unconditionally alongside scope-driven UI that
 * never actually invokes it for Platform. */
export function useForkSkill(scope: SkillScopeRef) {
  const queryClient = useQueryClient();
  const basePath = useSkillsBasePath(scope);

  return useMutation({
    mutationFn: async (skillId: string) => {
      const response = await api.post<SkillDetail>(`${basePath}/${skillId}/fork`, {}, { schema: SkillDetailSchema });
      return response.data;
    },
    onSuccess: (skill) => {
      queryClient.setQueryData(skillDraftKey(skill.id, scope), undefined);
      void queryClient.invalidateQueries({ queryKey: skillsKey.all });
    },
  });
}

/** Not applicable to Platform scope — Platform Skills have no source to update from. */
export function useApplySkillSourceUpdate(scope: SkillScopeRef) {
  const queryClient = useQueryClient();
  const basePath = useSkillsBasePath(scope);

  return useMutation({
    mutationFn: async (skillId: string) => {
      const response = await api.post<SkillDetail>(`${basePath}/${skillId}/source-update`, {}, { schema: SkillDetailSchema });
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: skillsKey.all });
    },
  });
}

/** Rename an owned lineage. Content/metadata changes are draft-gated, not here. */
export function useUpdateSkill(scope: SkillScopeRef) {
  const queryClient = useQueryClient();
  const basePath = useSkillsBasePath(scope);

  return useMutation({
    mutationFn: async ({ skillId, ...body }: SkillUpdatePayload) => {
      const response = await api.patch<Skill>(`${basePath}/${skillId}`, body, { schema: SkillSchema });
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: skillsKey.all });
    },
  });
}

/** Get-or-create the in-flight draft, seeded from the latest published version. */
export function useStartSkillDraft(scope: SkillScopeRef) {
  const queryClient = useQueryClient();
  const basePath = useSkillsBasePath(scope);

  return useMutation({
    mutationFn: async (skillId: string) => {
      const response = await api.post<SkillDraft>(`${basePath}/${skillId}/draft`, {}, { schema: SkillDraftSchema });
      return response.data;
    },
    onSuccess: (draft) => {
      queryClient.setQueryData(skillDraftKey(draft.skillId, scope), draft);
      void queryClient.invalidateQueries({ queryKey: skillsKey.all });
    },
  });
}

export type SkillDraftUpdatePayload = {
  skillId: string;
  files: SkillFilePayload[];
  description?: string | null;
  requiredProviders?: string[] | null;
};

export function useUpdateSkillDraft(scope: SkillScopeRef) {
  const queryClient = useQueryClient();
  const basePath = useSkillsBasePath(scope);

  return useMutation({
    mutationFn: async ({ skillId, files, ...metadata }: SkillDraftUpdatePayload) => {
      const response = await api.patch<SkillDraft>(`${basePath}/${skillId}/draft`, { files, ...metadata }, {
        schema: SkillDraftSchema,
      });
      return response.data;
    },
    onSuccess: (draft) => {
      queryClient.setQueryData(skillDraftKey(draft.skillId, scope), draft);
      void queryClient.invalidateQueries({ queryKey: skillsKey.all });
    },
  });
}

export function useDiscardSkillDraft(scope: SkillScopeRef) {
  const queryClient = useQueryClient();
  const basePath = useSkillsBasePath(scope);

  return useMutation({
    mutationFn: async (skillId: string) => {
      await api.delete(`${basePath}/${skillId}/draft`);
    },
    onSuccess: (_data, skillId) => {
      queryClient.removeQueries({ queryKey: skillDraftKey(skillId, scope) });
      void queryClient.invalidateQueries({ queryKey: skillsKey.all });
    },
  });
}

export function usePublishSkillDraft(scope: SkillScopeRef) {
  const queryClient = useQueryClient();
  const basePath = useSkillsBasePath(scope);

  return useMutation({
    mutationFn: async (skillId: string) => {
      const response = await api.post<Skill>(`${basePath}/${skillId}/draft/publish`, {}, { schema: SkillSchema });
      return response.data;
    },
    onSuccess: (skill) => {
      queryClient.removeQueries({ queryKey: skillDraftKey(skill.id, scope) });
      void queryClient.invalidateQueries({ queryKey: skillsKey.all });
    },
  });
}

export function useDeleteSkillVersion(scope: SkillScopeRef) {
  const queryClient = useQueryClient();
  const basePath = useSkillsBasePath(scope);

  return useMutation({
    mutationFn: async ({ skillId, version }: { skillId: string; version: number }) => {
      await api.delete(`${basePath}/${skillId}/versions/${version}`);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: skillsKey.all });
    },
  });
}
