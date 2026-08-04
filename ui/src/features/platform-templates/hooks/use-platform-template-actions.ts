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
import {
  platformTemplatePublishedKey,
  platformTemplateVersionsKey,
  platformTemplatesKey,
} from "../utils";

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
      queryClient.setQueryData(platformTemplatesKey.detail(data.templateSlug), data);
      void queryClient.invalidateQueries({ queryKey: platformTemplatesKey.lists() });
    },
  });
}

export function useStartPlatformTemplateDraft() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ slug, sourceVersion }: { slug: string; sourceVersion?: number }) => {
      const query = sourceVersion === undefined ? "" : `?source_version=${sourceVersion}`;
      const response = await api.post<PlatformTemplateDraft>(
        `/api/v1/platform/templates/${slug}/draft${query}`,
        undefined,
        { schema: PlatformTemplateDraftReadSchema },
      );
      return response.data;
    },
    onSuccess: (data) => {
      queryClient.setQueryData(platformTemplatesKey.detail(data.templateSlug), data);
      void queryClient.invalidateQueries({ queryKey: platformTemplatesKey.lists() });
    },
  });
}

export function useUpdatePlatformTemplateDraft() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ slug, ...data }: PlatformTemplateDraftFields & { slug: string }) => {
      const response = await api.patch<PlatformTemplateDraft>(
        `/api/v1/platform/templates/${slug}/draft`,
        data,
        { schema: PlatformTemplateDraftReadSchema },
      );
      return response.data;
    },
    onSuccess: (data) => {
      queryClient.setQueryData(platformTemplatesKey.detail(data.templateSlug), data);
      void queryClient.invalidateQueries({ queryKey: platformTemplatesKey.lists() });
    },
  });
}

export function useDiscardPlatformTemplateDraft() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (slug: string) => {
      await api.delete(`/api/v1/platform/templates/${slug}/draft`);
      return slug;
    },
    onSuccess: (slug) => {
      queryClient.removeQueries({ queryKey: platformTemplatesKey.detail(slug) });
      void queryClient.invalidateQueries({ queryKey: platformTemplatesKey.lists() });
    },
  });
}

export function usePublishPlatformTemplateDraft() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (slug: string) => {
      const response = await api.post<{ id: string; templateSlug: string; version: number }>(
        `/api/v1/platform/templates/${slug}/draft/publish`,
        undefined,
        { schema: PlatformTemplatePublishedReadSchema },
      );
      return response.data;
    },
    onSuccess: (data) => {
      queryClient.removeQueries({ queryKey: platformTemplatesKey.detail(data.templateSlug) });
      void queryClient.invalidateQueries({ queryKey: platformTemplatePublishedKey.detail(data.templateSlug) });
      void queryClient.invalidateQueries({ queryKey: platformTemplateVersionsKey.detail(data.templateSlug) });
      void queryClient.invalidateQueries({ queryKey: platformTemplatesKey.lists() });
    },
  });
}
