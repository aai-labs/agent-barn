"use client";

import { useMutation } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { IntegrationValidationResult, IntegrationValidationResultSchema } from "../schemas";

export function useValidateIntegration() {
  return useMutation({
    mutationFn: async ({
      agentId,
      provider,
    }: {
      agentId: string;
      provider: string;
    }): Promise<{ provider: string; result: IntegrationValidationResult }> => {
      const response = await api.post<IntegrationValidationResult>(
        `/api/v1/agents/${agentId}/integrations/${provider}/validate`,
        {},
        { schema: IntegrationValidationResultSchema },
      );
      return { provider, result: response.data };
    },
  });
}
