"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { agentsKey } from "@/features/agents/utils";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { api } from "@/shared/api";
import { createQueryKeyStructure } from "@/shared/query-keys";

import {
  type SshAssignments,
  type SshCredential,
  type SshCredentialList,
  SshAssignmentsSchema,
  SshCredentialListSchema,
  SshCredentialSchema,
} from "../schemas";

export const sshKey = createQueryKeyStructure("ssh");

export function useSshCredentials(page = 1, search = "") {
  const base = useOrganizationApiBase();
  const client = useQueryClient();
  const query = useQuery({
    queryKey: sshKey.list({ scope: { base }, filters: { page, search } }),
    queryFn: async () =>
      (
        await api.get<SshCredentialList>(
          `${base}/ssh-credentials?page=${page}&page_size=100&search=${encodeURIComponent(search)}`,
          { schema: SshCredentialListSchema },
        )
      ).data,
  });
  const mutation = useMutation({
    mutationFn: async ({
      id,
      data,
      remove,
    }: {
      id?: string;
      data?: object;
      remove?: boolean;
    }) => {
      if (remove) return api.delete(`${base}/ssh-credentials/${id}`);
      if (id)
        return api.put<SshCredential>(`${base}/ssh-credentials/${id}`, data, {
          schema: SshCredentialSchema,
        });
      return api.post<SshCredential>(`${base}/ssh-credentials`, data, {
        schema: SshCredentialSchema,
      });
    },
    onSettled: () => client.invalidateQueries({ queryKey: sshKey.all }),
  });
  return {
    credentials: query.data?.items ?? [],
    total: query.data?.total ?? 0,
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
    mutation,
  };
}

export function useAgentSsh(agentId: string) {
  const base = useOrganizationApiBase();
  const client = useQueryClient();
  const url = `${base}/agents/${agentId}/ssh-credentials`;
  const query = useQuery({
    queryKey: sshKey.detail(`${base}:${agentId}`),
    enabled: Boolean(agentId),
    queryFn: async () =>
      (await api.get<SshAssignments>(url, { schema: SshAssignmentsSchema }))
        .data,
  });
  const mutation = useMutation({
    mutationFn: (data: {
      credentialIds: string[];
      expectedRevision: number;
      restart: boolean;
    }) =>
      api.put<SshAssignments>(url, data, {
        schema: SshAssignmentsSchema,
        timeout: 120_000,
      }),
    onSettled: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: sshKey.all }),
        client.invalidateQueries({ queryKey: agentsKey.detail(agentId) }),
        client.invalidateQueries({ queryKey: agentsKey.lists() }),
        client.invalidateQueries({ queryKey: agentsKey.health(agentId) }),
      ]);
    },
  });
  return {
    data: query.data,
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
    mutation,
  };
}
