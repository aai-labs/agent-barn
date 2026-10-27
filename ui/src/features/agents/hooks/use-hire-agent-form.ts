"use client";

import { useState } from "react";

import { useOrganizationAgentSizes } from "@/features/agent-sizes/hooks/use-organization-agent-sizes";
import { useActiveOrgRole } from "@/features/organizations/hooks/use-active-org-role";

import {
  coerceBooleanFields,
  expandGithubContent,
  hasIncompleteIntegration,
  isSignInOnlyProvider,
  isAutoConfiguredProvider,
  type IntegrationDraft,
} from "../integrations";
import { formatAgentName } from "../naming";
import { provisioningFailureOf } from "../provisioning-failure";
import type { AgentProvisioningError, AgentTemplateRead } from "../schemas";
import { splitRequiredSkills } from "../utils";
import { useAgentNameSuggestion } from "./use-agent-name-suggestion";
import { useCreateAgent } from "./use-create-agent";
import { useModels } from "./use-models";
import { useStartAgent } from "./use-start-agent";
import { useTemplates } from "./use-templates";

export type HiredAgent = { id: string; name: string; role: string };

function credentialsForProviders(
  providers: string[],
  existing: IntegrationDraft[],
): IntegrationDraft[] {
  const existingByProvider = new Map(existing.map((draft) => [draft.provider, draft]));
  return providers.map(
    (provider) =>
      existingByProvider.get(provider) ?? {
        provider,
        content: {},
      },
  );
}

/**
 * The state and submit of hiring an Agent: create it from a template, then start it.
 * Shared by the hire dialog and onboarding's "Set up your agent" step, which lay the
 * same fields out differently.
 */
export function useHireAgentForm({ onHired, templatePagination }: {
  onHired: (agent: HiredAgent) => void;
  templatePagination?: { page: number; pageSize: number };
}) {
  const { templates, total: totalTemplates, isLoading: isLoadingTemplates, error: templatesError, refetch: reloadTemplates } = useTemplates(templatePagination);
  const createAgent = useCreateAgent();
  const startAgent = useStartAgent();
  const suggestion = useAgentNameSuggestion();
  const [manualName, setManualName] = useState<string | null>(null);
  // Selection pins the Template version and required Skills while the user browses
  // other API pages; it must not depend on the currently displayed query result.
  const [template, setTemplate] = useState<AgentTemplateRead | undefined>();
  const templateKey = template?.templateKey ?? "";
  const [agentType, setAgentType] = useState<"openclaw" | "hermes">("hermes");
  const [model, setModel] = useState<string | null>(null);
  const { defaultModel } = useModels();
  const [approvalMode, setApprovalMode] = useState<"manual" | "auto" | "off">("auto");
  // Offered only to Owners and Admins of an Organization the platform lets choose; anyone
  // else hires on the default without being asked.
  const { role } = useActiveOrgRole();
  const { agentSizes } = useOrganizationAgentSizes();
  const sizeChoices = (role === "OWNER" || role === "ADMIN") && agentSizes?.canChoose ? agentSizes.sizes : null;
  // null is the default, which is also what is preselected.
  const [agentSizeId, setAgentSizeId] = useState<string | null>(null);
  const [selectedSkillIds, setSelectedSkillIds] = useState<string[]>([]);
  const [skillCredentials, setSkillCredentials] = useState<IntegrationDraft[]>([]);
  const [groupChoices, setGroupChoices] = useState<Record<string, string[]>>({});
  const [error, setError] = useState<string | null>(null);
  const [provisioningFailure, setProvisioningFailure] =
    useState<AgentProvisioningError | null>(null);
  // Creation can succeed and the start still fail. Holding the Agent lets the retry
  // start that Agent instead of creating a second one.
  const [createdAgent, setCreatedAgent] = useState<{ id: string; name: string } | null>(null);

  const name = manualName ?? (suggestion.firstName
    ? formatAgentName(suggestion.firstName, template?.templateName)
    : "");
  const { standalone, groups } = splitRequiredSkills(template?.requiredSkills ?? []);
  const missingGroupChoice = groups.some((group) => !(groupChoices[group.key]?.length));
  const pending = createAgent.isPending || startAgent.isPending;
  const canHire =
    Boolean(template) &&
    Boolean(name.trim()) &&
    !missingGroupChoice &&
    !hasIncompleteIntegration(skillCredentials);

  function handleTemplateChange(nextKey: string) {
    const nextTemplate = templates.find((candidate) => candidate.templateKey === nextKey);
    setTemplate(nextTemplate);
    setError(null);

    if (!nextTemplate) {
      setSelectedSkillIds([]);
      setSkillCredentials([]);
      setGroupChoices({});
      return;
    }

    const { standalone: nextStandalone } = splitRequiredSkills(nextTemplate.requiredSkills);
    const requiredProviders = [
      ...new Set(nextStandalone.flatMap((skill) => skill.requiredProviders)),
    ].filter((provider) => !isAutoConfiguredProvider(provider));
    setSelectedSkillIds(nextStandalone.map((skill) => skill.id));
    setGroupChoices({});
    setSkillCredentials((current) => credentialsForProviders(requiredProviders, current));
  }

  function handleGroupChoiceChange(groupKey: string, skillId: string) {
    setGroupChoices((current) => {
      const selected = current[groupKey] ?? [];
      const next = selected.includes(skillId)
        ? selected.filter((id) => id !== skillId)
        : [...selected, skillId];
      return { ...current, [groupKey]: next };
    });
  }

  async function hire() {
    if (!template || !canHire) return;
    setError(null);
    setProvisioningFailure(null);

    if (createdAgent) {
      await startCreatedAgent(createdAgent);
      return;
    }

    const skillIds = [
      ...new Set([
        ...selectedSkillIds,
        ...Object.values(groupChoices).flat(),
      ]),
    ];
    const requiredSkillVersions = [
      ...standalone,
      ...groups.flatMap((group) =>
        (groupChoices[group.key] ?? [])
          .map((id) => group.members.find((member) => member.id === id))
          .filter((skill): skill is (typeof standalone)[number] => skill !== undefined),
      ),
    ].map((skill) => ({ skillId: skill.id, version: skill.version }));
    const manualSecrets = skillCredentials
      .filter(
        (draft) =>
          !draft.sharedCredentialId &&
          !isAutoConfiguredProvider(draft.provider) &&
          !isSignInOnlyProvider(draft.provider),
      )
      .map((draft) => ({
        provider: draft.provider,
        content: coerceBooleanFields(
          draft.provider === "github"
            ? expandGithubContent(draft.content)
            : draft.content,
        ),
      }));
    const sharedCredentials = skillCredentials
      .filter((draft) => draft.sharedCredentialId)
      .map((draft) => ({ sharedCredentialId: draft.sharedCredentialId! }));

    try {
      const approval = agentType === "hermes" ? { approvalMode } : {};
      const agent = await createAgent.mutateAsync({
        name: name.trim(),
        agentType,
        templateKey: template.templateKey,
        templateVersion: template.version,
        ...(model ? { model } : {}),
        ...(skillIds.length > 0 ? { skillIds } : {}),
        ...(requiredSkillVersions.length > 0 ? { skillVersions: requiredSkillVersions } : {}),
        ...(manualSecrets.length > 0 ? { secrets: manualSecrets } : {}),
        ...(sharedCredentials.length > 0 ? { sharedCredentials } : {}),
        ...approval,
        ...(sizeChoices && agentSizeId ? { agentSizeId } : {}),
      });
      setCreatedAgent({ id: agent.id, name: agent.name });
      await startCreatedAgent({ id: agent.id, name: agent.name });
    } catch (cause) {
      reportHireFailure(cause);
    }
  }

  async function startCreatedAgent(agent: { id: string; name: string }) {
    if (!template) return;
    try {
      await startAgent.mutateAsync(agent.id);
      onHired({ id: agent.id, name: agent.name, role: template.templateName });
    } catch (cause) {
      reportHireFailure(cause);
    }
  }

  function reportHireFailure(cause: unknown) {
    const failure = provisioningFailureOf(cause);
    if (failure) {
      setProvisioningFailure(failure);
      return;
    }
    setError(cause instanceof Error ? cause.message : "Could not hire the Agent.");
  }

  return {
    templates,
    totalTemplates,
    isLoadingTemplates,
    templatesError,
    reloadTemplates,
    template,
    templateKey,
    handleTemplateChange,
    name,
    setName: setManualName,
    suggestion,
    agentType,
    setAgentType,
    model,
    setModel,
    defaultModel,
    approvalMode,
    setApprovalMode,
    sizeChoices,
    agentSizeId,
    setAgentSizeId,
    selectedSkillIds,
    setSelectedSkillIds,
    skillCredentials,
    setSkillCredentials,
    groupChoices,
    handleGroupChoiceChange,
    standalone,
    groups,
    error,
    provisioningFailure,
    createdAgent,
    pending,
    canHire,
    hire,
  };
}
