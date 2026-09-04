"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";

import {
  PlatformTemplateDraftReadSchema,
  PlatformTemplatePublishedReadSchema,
  type CreatePlatformTemplateDraft,
  type PlatformTemplateDraft,
  type PlatformTemplateDraftFields,
} from "../schemas";
import { useTemplatesBasePath, type TemplateScopeRef } from "../scope";
import { templateDraftKey, templateLineagesKey, templateVersionsKey } from "../utils";

export function useCreateTemplateDraft(scope: TemplateScopeRef) {
  const queryClient = useQueryClient();
  const basePath = useTemplatesBasePath(scope);

  return useMutation({
    mutationFn: async (data: CreatePlatformTemplateDraft) => {
      const response = await api.post<PlatformTemplateDraft>(basePath, data, {
        schema: PlatformTemplateDraftReadSchema,
      });
      return response.data;
    },
    onSuccess: (data) => {
      queryClient.setQueryData(templateDraftKey(data.templateKey, scope), data);
      void queryClient.invalidateQueries({ queryKey: templateLineagesKey(scope) });
    },
  });
}

export function useStartTemplateDraft(scope: TemplateScopeRef) {
  const queryClient = useQueryClient();
  const basePath = useTemplatesBasePath(scope);

  return useMutation({
    mutationFn: async ({
      templateKey,
      sourceVersion,
    }: {
      templateKey: string;
      sourceVersion?: number;
    }) => {
      const query = sourceVersion === undefined ? "" : `?source_version=${sourceVersion}`;
      const response = await api.post<PlatformTemplateDraft>(
        `${basePath}/${templateKey}/draft${query}`,
        undefined,
        { schema: PlatformTemplateDraftReadSchema },
      );
      return response.data;
    },
    onSuccess: (data) => {
      queryClient.setQueryData(templateDraftKey(data.templateKey, scope), data);
      void queryClient.invalidateQueries({ queryKey: templateLineagesKey(scope) });
    },
  });
}

export function useUpdateTemplateDraft(scope: TemplateScopeRef) {
  const queryClient = useQueryClient();
  const basePath = useTemplatesBasePath(scope);

  return useMutation({
    mutationFn: async ({
      templateKey,
      ...data
    }: PlatformTemplateDraftFields & { templateKey: string }) => {
      const response = await api.patch<PlatformTemplateDraft>(
        `${basePath}/${templateKey}/draft`,
        data,
        { schema: PlatformTemplateDraftReadSchema },
      );
      return response.data;
    },
    onSuccess: (data) => {
      queryClient.setQueryData(templateDraftKey(data.templateKey, scope), data);
      void queryClient.invalidateQueries({ queryKey: templateLineagesKey(scope) });
    },
  });
}

export function useDiscardTemplateDraft(scope: TemplateScopeRef) {
  const queryClient = useQueryClient();
  const basePath = useTemplatesBasePath(scope);

  return useMutation({
    mutationFn: async (templateKey: string) => {
      await api.delete(`${basePath}/${templateKey}/draft`);
      return templateKey;
    },
    onSuccess: (templateKey) => {
      queryClient.removeQueries({ queryKey: templateDraftKey(templateKey, scope) });
      void queryClient.invalidateQueries({ queryKey: templateLineagesKey(scope) });
    },
  });
}

export function usePublishTemplateDraft(scope: TemplateScopeRef) {
  const queryClient = useQueryClient();
  const basePath = useTemplatesBasePath(scope);

  return useMutation({
    mutationFn: async (templateKey: string) => {
      const response = await api.post<{ id: string; templateKey: string; version: number }>(
        `${basePath}/${templateKey}/draft/publish`,
        undefined,
        { schema: PlatformTemplatePublishedReadSchema },
      );
      return response.data;
    },
    onSuccess: (data) => {
      queryClient.removeQueries({ queryKey: templateDraftKey(data.templateKey, scope) });
      void queryClient.invalidateQueries({ queryKey: templateVersionsKey(data.templateKey, scope) });
      void queryClient.invalidateQueries({ queryKey: templateLineagesKey(scope) });
    },
  });
}
