"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import { SharedCredentialReadSchema, type SharedCredentialRead } from "../schemas";
import { sharedCredentialsKey } from "../utils";

export type SharedCredentialCreatePayload = {
  provider: string;
  name: string;
  content: Record<string, string | string[]>;
};

export type SharedCredentialUpdatePayload = {
  credentialId: string;
  name?: string;
  content?: Record<string, string | string[]>;
};

export function useCreateSharedCredential() {
  const queryClient = useQueryClient();
  const orgApiBase = useOrganizationApiBase();

  return useMutation({
    mutationFn: async ({ ...body }: SharedCredentialCreatePayload) => {
      const response = await api.post<SharedCredentialRead>(
        `${orgApiBase}/shared-credentials`,
        body,
        { schema: SharedCredentialReadSchema },
      );
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: sharedCredentialsKey.all,
      });
    },
  });
}

export function useUpdateSharedCredential() {
  const queryClient = useQueryClient();
  const orgApiBase = useOrganizationApiBase();

  return useMutation({
    mutationFn: async ({ credentialId, ...body }: SharedCredentialUpdatePayload) => {
      const response = await api.patch<SharedCredentialRead>(
        `${orgApiBase}/shared-credentials/${credentialId}`,
        body,
        { schema: SharedCredentialReadSchema },
      );
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: sharedCredentialsKey.all,
      });
    },
  });
}

export function useDeleteSharedCredential() {
  const queryClient = useQueryClient();
  const orgApiBase = useOrganizationApiBase();

  return useMutation({
    mutationFn: async (credentialId: string) => {
      await api.delete(`${orgApiBase}/shared-credentials/${credentialId}`);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: sharedCredentialsKey.all,
      });
    },
  });
}

export function useValidateSharedCredential() {
  const orgApiBase = useOrganizationApiBase();

  return useMutation({
    mutationFn: async (credentialId: string) => {
      const response = await api.post(
        `${orgApiBase}/shared-credentials/${credentialId}/validate`,
        {},
      );
      return response.data;
    },
  });
}
