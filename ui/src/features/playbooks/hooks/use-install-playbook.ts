"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { AgentSchema, type Agent } from "@/features/agents/schemas";
import { agentsKey } from "@/features/agents/utils";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { useStartTemplateDraft, useUpdateTemplateDraft } from "@/features/templates/hooks/use-template-actions";
import { api } from "@/shared/api";
import { getErrorDisplay } from "@/shared/api/error/get-error-display";

export type AgentInstallResult = { agentId: string; ok: boolean; message?: string };

const ORGANIZATION_TEMPLATES = { kind: "organization" } as const;

/**
 * Add a published playbook to Agents, or move Agents that already have it to this
 * version. Each Agent is updated separately so one refusal, such as a missing
 * provider credential, does not block the others.
 */
export function useAddPlaybookToAgents(skillId: string, version: number) {
  const orgApiBase = useOrganizationApiBase();
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (agents: Pick<Agent, "id" | "skills">[]): Promise<AgentInstallResult[]> => {
      const results: AgentInstallResult[] = [];
      for (const agent of agents) {
        const assigned = agent.skills.some((skill) => skill.id === skillId);
        try {
          await api.patch<Agent>(
            `${orgApiBase}/agents/${agent.id}`,
            {
              ...(assigned ? {} : { skillIds: [skillId] }),
              skillVersions: [{ skillId, version }],
            },
            { schema: AgentSchema },
          );
          results.push({ agentId: agent.id, ok: true });
        } catch (caught) {
          results.push({ agentId: agent.id, ok: false, message: getErrorDisplay(caught).description });
        }
      }
      return results;
    },
    onSettled: () => client.invalidateQueries({ queryKey: agentsKey.all }),
  });
}

/**
 * Add a published playbook to an Organization Template's draft, starting the draft
 * from the latest version when none exists. Publishing stays with the person, in
 * the Template editor; Agents created from the next version receive the playbook.
 */
export function useRequirePlaybookOnTemplate(skillId: string, version: number) {
  const startDraft = useStartTemplateDraft(ORGANIZATION_TEMPLATES);
  const updateDraft = useUpdateTemplateDraft(ORGANIZATION_TEMPLATES);
  return useMutation({
    mutationFn: async (templateKey: string): Promise<{ templateKey: string; alreadyRequired: boolean }> => {
      const draft = await startDraft.mutateAsync({ templateKey });
      if (draft.requiredSkills.some((skill) => skill.id === skillId)) {
        return { templateKey, alreadyRequired: true };
      }
      const standalone = draft.requiredSkills.filter((skill) => skill.groupKey === null).map((skill) => skill.id);
      // Omitted groups and the other Skills' pins are kept by the server.
      await updateDraft.mutateAsync({
        templateKey,
        requiredSkillIds: [...standalone, skillId],
        requiredSkillVersions: { [skillId]: version },
      });
      return { templateKey, alreadyRequired: false };
    },
  });
}
