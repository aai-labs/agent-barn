"use client";

import { useState } from "react";
import { XIcon } from "@/components/icons";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import {
  coerceBooleanFields,
  expandGithubContent,
  hasIncompleteIntegration,
  isAutoConfiguredProvider,
  type IntegrationDraft,
} from "../integrations";
import { useCreateAgent } from "../hooks/use-create-agent";
import { useStartAgent } from "../hooks/use-start-agent";
import { useModels } from "../hooks/use-models";
import { useTemplates } from "../hooks/use-templates";
import { splitRequiredSkills } from "../utils";
import { CredentialErrorAlert } from "./credential-error-alert";
import {
  describeProvisioningFailure,
  provisioningFailureOf,
  type ProvisioningFailureDisplay,
} from "../provisioning-failure";
import { DialogShell, FormField } from "./hire-dialog-primitives";
import { SkillsStep } from "./hire-dialog-steps";
import { ModelChoice } from "./model-choice";

const DEFAULT_AGENT_NAME = "Aria";

interface HireDialogProps {
  onClose: () => void;
  onHired: (info: { name: string; role: string }) => void;
}

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

export function HireDialog({ onClose, onHired }: HireDialogProps) {
  const { templates, isLoading } = useTemplates();
  const createAgent = useCreateAgent();
  const startAgent = useStartAgent();
  const [name, setName] = useState(DEFAULT_AGENT_NAME);
  const [templateKey, setTemplateKey] = useState("");
  const [agentType, setAgentType] = useState<"openclaw" | "hermes">("hermes");
  const [model, setModel] = useState<string | null>(null);
  const { defaultModel } = useModels();
  const [approvalMode, setApprovalMode] = useState<"manual" | "auto" | "off">("auto");
  const [selectedSkillIds, setSelectedSkillIds] = useState<string[]>([]);
  const [skillCredentials, setSkillCredentials] = useState<IntegrationDraft[]>([]);
  const [groupChoices, setGroupChoices] = useState<Record<string, string[]>>({});
  const [error, setError] = useState<string | null>(null);
  const [provisioningFailure, setProvisioningFailure] =
    useState<ProvisioningFailureDisplay | null>(null);
  // Creation can succeed and the start still fail. Holding the Agent lets the retry
  // start that Agent instead of creating a second one.
  const [createdAgent, setCreatedAgent] = useState<{ id: string; name: string } | null>(null);

  const template = templates.find((candidate) => candidate.templateKey === templateKey);
  const { standalone, groups } = splitRequiredSkills(template?.requiredSkills ?? []);
  const missingGroupChoice = groups.some((group) => !(groupChoices[group.key]?.length));
  const pending = createAgent.isPending || startAgent.isPending;
  const canHire =
    Boolean(template) &&
    !missingGroupChoice &&
    !hasIncompleteIntegration(skillCredentials);

  const hireButtonLabel = createdAgent
    ? pending
      ? "Starting…"
      : "Start again"
    : pending
      ? "Hiring…"
      : "Hire Agent";

  function handleTemplateChange(nextKey: string) {
    const nextTemplate = templates.find((candidate) => candidate.templateKey === nextKey);
    setTemplateKey(nextKey);
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
    if (!template || !name.trim() || !canHire) return;
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
      .filter((draft) => !draft.sharedCredentialId && !isAutoConfiguredProvider(draft.provider))
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
      onHired({ name: agent.name, role: template.templateName });
    } catch (cause) {
      reportHireFailure(cause);
    }
  }

  function reportHireFailure(cause: unknown) {
    const failure = provisioningFailureOf(cause);
    if (failure) {
      setProvisioningFailure(describeProvisioningFailure(failure));
      return;
    }
    setError(cause instanceof Error ? cause.message : "Could not hire the Agent.");
  }

  return (
    <DialogShell shadeClick={pending ? undefined : onClose}>
      <header className="flex items-start justify-between border-b px-6 py-5" style={{ borderColor: "var(--line)" }}>
        <div>
          <div className="mb-1 text-xs font-semibold uppercase tracking-[0.08em]" style={{ color: "var(--ink-3)" }}>New Agent</div>
          <h2 className="m-0 text-xl font-semibold tracking-tight">Hire a headless Agent</h2>
          <p className="mb-0 mt-1 text-sm" style={{ color: "var(--ink-3)" }}>Start with the runtime. Add a messaging platform or several connections afterward.</p>
        </div>
        <button type="button" className="af-btn af-btn-ghost af-btn-icon" disabled={pending} onClick={onClose}><XIcon /></button>
      </header>

      <div className="grid flex-1 gap-5 overflow-y-auto p-6 sm:grid-cols-2">
        {!createdAgent && (
          <>
        <FormField label="Agent name">
          <input className="af-input" value={name} onChange={(event) => setName(event.target.value)} autoFocus />
        </FormField>
        <FormField label="Runtime">
          <Select value={agentType} onValueChange={(value) => setAgentType(value as "openclaw" | "hermes")}>
            <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
            <SelectContent><SelectGroup><SelectItem value="hermes">Hermes</SelectItem><SelectItem value="openclaw">OpenClaw</SelectItem></SelectGroup></SelectContent>
          </Select>
        </FormField>
        <FormField label="Template" hint="Communication connections do not belong to templates or runtimes.">
          <Select value={templateKey} onValueChange={handleTemplateChange} disabled={isLoading || pending}>
            <SelectTrigger className="w-full"><SelectValue placeholder={isLoading ? "Loading templates…" : "Choose a template"} /></SelectTrigger>
            <SelectContent><SelectGroup>{templates.map((item) => <SelectItem key={`${item.templateKey}:${item.version}`} value={item.templateKey}>{item.templateName} · v{item.version}</SelectItem>)}</SelectGroup></SelectContent>
          </Select>
        </FormField>
        <FormField label="Model">
          <ModelChoice
            value={model}
            effectiveDefaultModel={defaultModel}
            onChange={setModel}
            disabled={pending}
          />
        </FormField>
        {agentType === "hermes" && (
          <FormField label="Command approval">
            <Select value={approvalMode} onValueChange={(value) => setApprovalMode(value as "manual" | "auto" | "off")} disabled={pending}>
              <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent><SelectGroup><SelectItem value="auto">Automatic</SelectItem><SelectItem value="manual">Manual</SelectItem><SelectItem value="off">Off</SelectItem></SelectGroup></SelectContent>
            </Select>
          </FormField>
        )}
        <div className="rounded-xl border border-dashed p-4 text-sm" style={{ color: "var(--ink-3)" }}>
          {template?.requiredSkills.length
            ? "Communication connections are configured after hiring. Credentials required by this template are configured before hiring."
            : "Communication connections and integration credentials are configured independently after hiring."}
        </div>

        {template && template.requiredSkills.length > 0 && (
          <section className="flex flex-col gap-3 border-t pt-5 sm:col-span-2" style={{ borderColor: "var(--line)" }}>
            <div>
              <h3 className="m-0 text-base font-semibold" style={{ color: "var(--ink)" }}>Template skills and credentials</h3>
              <p className="mb-0 mt-1 text-sm" style={{ color: "var(--ink-3)" }}>
                Required skills are assigned as part of creation. Their credentials are validated by the server before anything is saved.
              </p>
            </div>
            <SkillsStep
              key={`${template.templateKey}:${template.version}`}
              selectedSkillIds={selectedSkillIds}
              skillCredentials={skillCredentials}
              onSkillIdsChange={setSelectedSkillIds}
              onSkillCredentialsChange={setSkillCredentials}
              templateRequiredSkills={standalone}
              requiredGroups={groups}
              groupChoices={groupChoices}
              onGroupChoiceChange={handleGroupChoiceChange}
              credentialError={error}
            />
          </section>
        )}
          </>
        )}

        {provisioningFailure && (
          <div
            role="alert"
            data-testid="hire-provisioning-error"
            className="rounded-xl px-4 py-3.5 text-[0.8125rem] sm:col-span-2"
            style={{
              background: "color-mix(in srgb, var(--err) 10%, transparent)",
              border: "1px solid color-mix(in srgb, var(--err) 25%, transparent)",
              color: "var(--err)",
            }}
          >
            <p className="m-0 font-medium">{provisioningFailure.title}</p>
            <p className="m-0 mt-1">{provisioningFailure.summary}</p>
            {provisioningFailure.detail && (
              <p className="m-0 mt-2 overflow-x-auto font-mono text-[0.75rem] leading-[1.5] opacity-80">
                {provisioningFailure.detail}
              </p>
            )}
            {/* The Agent was created before the start failed, so it is on the
                team page in ERROR rather than lost. Saying so stops the reader
                hiring a second one to replace it. */}
            <p className="m-0 mt-2 opacity-90">
              {name.trim()} was created and is waiting on your team page.
            </p>
          </div>
        )}

        {error && (!template?.requiredSkills.length || skillCredentials.length === 0) && (
          <CredentialErrorAlert
            title="Could not hire Agent"
            message={error}
          />
        )}
      </div>

      <footer className="flex justify-end gap-2 border-t px-6 py-4" style={{ borderColor: "var(--line)" }}>
        <button type="button" className="af-btn" disabled={pending} onClick={onClose}>Cancel</button>
        <button type="button" className="af-btn af-btn-primary" disabled={pending || !template || !name.trim() || !canHire} onClick={() => void hire()}>
          {hireButtonLabel}
        </button>
      </footer>
    </DialogShell>
  );
}
