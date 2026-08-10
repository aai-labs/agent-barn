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
import { platformTemplateVersionsKey, platformTemplatesKey } from "../utils";

export function useCreatePlatformTemplateDraft() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (data: CreatePlatformTemplateDraft) => {
      const response = await api.post<PlatformTemplateDraft>(
        "/api/v1/platform/templates",
        data,
        { schema: PlatformTemplateDraftReadSchema },
      );
      return response.data;
    },
    onSuccess: (data) => {
      queryClient.setQueryData(platformTemplatesKey.detail(data.templateKey), data);
      void queryClient.invalidateQueries({ queryKey: platformTemplatesKey.lists() });
    },
  });
}

export function useStartPlatformTemplateDraft() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ templateKey, sourceVersion }: { templateKey: string; sourceVersion?: number }) => {
      const query = sourceVersion === undefined ? "" : `?source_version=${sourceVersion}`;
      const response = await api.post<PlatformTemplateDraft>(
        `/api/v1/platform/templates/${templateKey}/draft${query}`,
        undefined,
        { schema: PlatformTemplateDraftReadSchema },
      );
      return response.data;
    },
    onSuccess: (data) => {
      queryClient.setQueryData(platformTemplatesKey.detail(data.templateKey), data);
      void queryClient.invalidateQueries({ queryKey: platformTemplatesKey.lists() });
    },
  });
}

export function useUpdatePlatformTemplateDraft() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ templateKey, ...data }: PlatformTemplateDraftFields & { templateKey: string }) => {
      const response = await api.patch<PlatformTemplateDraft>(
        `/api/v1/platform/templates/${templateKey}/draft`,
        data,
        { schema: PlatformTemplateDraftReadSchema },
      );
      return response.data;
    },
    onSuccess: (data) => {
      queryClient.setQueryData(platformTemplatesKey.detail(data.templateKey), data);
      void queryClient.invalidateQueries({ queryKey: platformTemplatesKey.lists() });
    },
  });
}

export function useDiscardPlatformTemplateDraft() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (templateKey: string) => {
      await api.delete(`/api/v1/platform/templates/${templateKey}/draft`);
      return templateKey;
    },
    onSuccess: (templateKey) => {
      queryClient.removeQueries({ queryKey: platformTemplatesKey.detail(templateKey) });
      void queryClient.invalidateQueries({ queryKey: platformTemplatesKey.lists() });
    },
  });
}

export function usePublishPlatformTemplateDraft() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (templateKey: string) => {
      const response = await api.post<{ id: string; templateKey: string; version: number }>(
        `/api/v1/platform/templates/${templateKey}/draft/publish`,
        undefined,
        { schema: PlatformTemplatePublishedReadSchema },
      );
      return response.data;
    },
    onSuccess: (data) => {
      queryClient.removeQueries({ queryKey: platformTemplatesKey.detail(data.templateKey) });
      void queryClient.invalidateQueries({ queryKey: platformTemplateVersionsKey.detail(data.templateKey) });
      void queryClient.invalidateQueries({ queryKey: platformTemplatesKey.lists() });
    },
  });
}
