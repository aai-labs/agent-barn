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

  const template = templates.find((candidate) => candidate.templateKey === templateKey);
  const { standalone, groups } = splitRequiredSkills(template?.requiredSkills ?? []);
  const missingGroupChoice = groups.some((group) => !(groupChoices[group.key]?.length));
  const pending = createAgent.isPending || startAgent.isPending;
  const canHire =
    Boolean(template) &&
    !missingGroupChoice &&
    !hasIncompleteIntegration(skillCredentials);

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
      await startAgent.mutateAsync(agent.id);
      onHired({ name: agent.name, role: template.templateName });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not hire the Agent.");
    }
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
          {pending ? "Hiring…" : "Hire Agent"}
        </button>
      </footer>
    </DialogShell>
  );
}
