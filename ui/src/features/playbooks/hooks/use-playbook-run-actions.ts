"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { skillsKey } from "@/features/skills/utils";
import { api } from "@/shared/api";

import { PlaybookExtractionSchema, type PlaybookExtraction, type PlaybookExtractionCreate } from "../schemas";
import { playbooksKey } from "../utils";

function useInvalidateRuns(agentId: string) {
  const client = useQueryClient();
  return async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: playbooksKey.agentRuns(agentId) }),
      client.invalidateQueries({ queryKey: playbooksKey.all }),
      // A finished run creates a Skill or its draft.
      client.invalidateQueries({ queryKey: skillsKey.all }),
    ]);
  };
}

export function useStartPlaybookExtraction(agentId: string) {
  const orgApiBase = useOrganizationApiBase();
  const invalidate = useInvalidateRuns(agentId);
  return useMutation({
    mutationFn: async (body: PlaybookExtractionCreate) =>
      (
        await api.post<PlaybookExtraction>(`${orgApiBase}/agents/${agentId}/playbook-extractions`, body, {
          schema: PlaybookExtractionSchema,
        })
      ).data,
    onSettled: invalidate,
  });
}

export function useCancelPlaybookExtraction(agentId: string) {
  const orgApiBase = useOrganizationApiBase();
  const invalidate = useInvalidateRuns(agentId);
  return useMutation({
    mutationFn: async (runId: string) =>
      (
        await api.post<PlaybookExtraction>(
          `${orgApiBase}/agents/${agentId}/playbook-extractions/${runId}/cancel`,
          {},
          { schema: PlaybookExtractionSchema },
        )
      ).data,
    onSettled: invalidate,
  });
}
