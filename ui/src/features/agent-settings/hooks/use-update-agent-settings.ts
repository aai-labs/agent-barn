"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { toastError } from "@/shared/toast";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";
import { agentsKey } from "@/features/agents/utils";

import { AgentSettingsSchema, type AgentSettings, type AgentSettingsUpdate } from "../schemas";
import { agentSettingsKey } from "../utils";

/**
 * `toastOnError: false` for callers that render the failure inline — a default rejected
 * for sitting outside the allowlist belongs next to the picker that offered it.
 */
export function useUpdateAgentSettings({ toastOnError = true }: { toastOnError?: boolean } = {}) {
  const orgApiBase = useOrganizationApiBase();
  const { selectedOrganization } = useOrganizationContext();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (data: AgentSettingsUpdate) => {
      const response = await api.put<AgentSettings>(`${orgApiBase}/agent-settings`, data, {
        schema: AgentSettingsSchema,
      });
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: agentSettingsKey.detail(selectedOrganization?.id ?? ""),
      });
      // Every Agent's resolved model and inherit/override badge can move with the
      // default, and the model picker flags the default it now points at.
      void queryClient.invalidateQueries({ queryKey: agentsKey.all });
      void queryClient.invalidateQueries({ queryKey: agentsKey.models() });
    },
    onError: toastOnError
      ? (error: Error) => {
          toastError(error, "Failed to save Agent defaults. Please try again.");
        }
      : undefined,
  });
}
