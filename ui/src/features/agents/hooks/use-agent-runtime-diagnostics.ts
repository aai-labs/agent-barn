"use client";

import { useQuery } from "@tanstack/react-query";

import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { api } from "@/shared/api";

import { AgentRuntimeDiagnosticsSchema, type AgentRuntimeDiagnostics } from "../schemas";
import { agentsKey } from "../utils";

export function useAgentRuntimeDiagnostics(agentId: string) {
  const orgApiBase = useOrganizationApiBase();
  return useQuery({
    queryKey: agentsKey.diagnostics(orgApiBase, agentId),
    queryFn: async () => (await api.get<AgentRuntimeDiagnostics>(
      `${orgApiBase}/agents/${agentId}/diagnostics`,
      { schema: AgentRuntimeDiagnosticsSchema },
    )).data,
    enabled: !!agentId,
    retry: false,
    refetchOnWindowFocus: false,
  });
}
