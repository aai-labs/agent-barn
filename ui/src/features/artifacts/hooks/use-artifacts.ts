"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";
import { api } from "@/shared/api";
import { artifactsKey } from "@/shared/query-keys";
import {
  ArtifactStorageSchema,
  type ArtifactStorage,
  ArtifactListSchema,
  ArtifactLinkSchema,
  type ArtifactList,
  type ArtifactLink,
} from "../schemas";

export function useArtifacts(agentId: string, runId?: string, stepId?: string, polling = false) {
  const organizationId = useOrganizationContext().selectedOrganization?.id ?? "";
  const base = `${useOrganizationApiBase()}/agents/${agentId}/artifacts`;
  const files = useInfiniteQuery({
    queryKey: artifactsKey.list({
      scope: { organizationId, agentId },
      filters: { runId, stepId, infinite: true },
    }),
    queryFn: async ({ pageParam }) => {
      const parameters = new URLSearchParams({ page: String(pageParam), page_size: "20" });
      if (runId) parameters.set("run_id", runId);
      if (stepId) parameters.set("step_id", stepId);
      return (await api.get<ArtifactList>(`${base}?${parameters}`, { schema: ArtifactListSchema })).data;
    },
    enabled: Boolean(organizationId && agentId),
    refetchOnWindowFocus: true,
    refetchInterval: (query) => polling && !query.state.error ? 5000 : false,
    initialPageParam: 1,
    getNextPageParam: last => last.page * last.pageSize < last.total ? last.page + 1 : undefined,

  });
  const download = useMutation({
    mutationFn: async (artifactId: string) => (
      await api.get<ArtifactLink>(`${base}/${artifactId}/download-link`, { schema: ArtifactLinkSchema })
    ).data,
    onSuccess: (link) => { window.location.assign(link.url); },
  });
  return { files, download };
}

export function useArtifactStorage(agentId: string) {
  const organizationId = useOrganizationContext().selectedOrganization?.id ?? "";
  const base = `${useOrganizationApiBase()}/agents/${agentId}/artifacts/storage`;
  const client = useQueryClient();
  const key = artifactsKey.list({ scope: { organizationId, agentId }, filters: { resource: "storage" } });
  const storage = useQuery({
    queryKey: key,
    enabled: Boolean(organizationId && agentId),
    queryFn: async () => (await api.get<ArtifactStorage>(base, { schema: ArtifactStorageSchema })).data,
    refetchInterval: query => ["PROVISIONING", "FAILED"].includes(query.state.data?.state ?? "") && !query.state.error ? 2000 : false,
  });
  const provision = useMutation({
    mutationFn: async () => (await api.post<ArtifactStorage>(base, {}, { schema: ArtifactStorageSchema })).data,
    onSuccess: async status => {
      client.setQueryData(key, status);
      await client.invalidateQueries({ queryKey: artifactsKey.all });
    },
  });
  return { storage, provision };
}
