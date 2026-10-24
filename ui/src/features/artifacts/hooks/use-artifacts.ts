"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";
import { api } from "@/shared/api";
import { artifactsKey } from "@/shared/query-keys";
import {
  ArtifactListSchema,
  ArtifactLinkSchema,
  type ArtifactList,
  type ArtifactLink,
} from "../schemas";

export function useArtifacts(agentId: string, page: number, runId?: string, stepId?: string, polling = false) {
  const organizationId = useOrganizationContext().selectedOrganization?.id ?? "";
  const base = `${useOrganizationApiBase()}/agents/${agentId}/artifacts`;
  const parameters = new URLSearchParams({ page: String(page) });
  if (runId) parameters.set("run_id", runId);
  if (stepId) parameters.set("step_id", stepId);
  const files = useQuery({
    queryKey: artifactsKey.list({
      scope: { organizationId, agentId },
      filters: { page, runId, stepId },
    }),
    enabled: Boolean(organizationId && agentId),
    refetchOnWindowFocus: true,
    refetchInterval: (query) => polling && !query.state.error ? 5000 : false,
    queryFn: async () => (
      await api.get<ArtifactList>(`${base}?${parameters}`, { schema: ArtifactListSchema })
    ).data,
  });
  const download = useMutation({
    mutationFn: async (artifactId: string) => (
      await api.get<ArtifactLink>(`${base}/${artifactId}/download-link`, { schema: ArtifactLinkSchema })
    ).data,
    onSuccess: (link) => { window.location.assign(link.url); },
  });
  return { files, download };
}
