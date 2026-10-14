"use client";

import { XIcon } from "@/components/icons";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useOrganization } from "@/features/organizations/hooks/use-organization";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";

import { useAgents } from "../hooks/use-agents";
import { useHireAgentForm, type HiredAgent } from "../hooks/use-hire-agent-form";
import { CredentialErrorAlert } from "./credential-error-alert";
import { AgentErrorBanner } from "./agent-error-banner";
import { DialogShell, FormField } from "./hire-dialog-primitives";
import { SkillsStep } from "./hire-dialog-steps";
import { ModelChoice } from "./model-choice";

interface HireDialogProps {
  onClose: () => void;
  onHired: (agent: HiredAgent) => void;
}

export function HireDialog({ onClose, onHired }: HireDialogProps) {
  const { selectedOrganization } = useOrganizationContext();
  // The membership list doesn't carry a trial's agent limit; the organization read does.
  const { organization } = useOrganization(selectedOrganization?.isTrial ? selectedOrganization.id : "");
  const trialAgentLimit = organization?.trialAgentLimit ?? null;
  const { total: agentCount } = useAgents();
  const {
    templates,
    isLoadingTemplates: isLoading,
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
  } = useHireAgentForm({ onHired });

  const hireButtonLabel = createdAgent
    ? pending
      ? "Starting…"
      : "Start again"
    : pending
      ? "Hiring…"
      : "Hire Agent";

  // A trial at its agent limit is refused by the API, so say so before the form.
  if (selectedOrganization?.isTrial && trialAgentLimit != null && agentCount >= trialAgentLimit) {
    return (
      <DialogShell shadeClick={onClose}>
        <header className="flex items-start justify-between border-b px-6 py-5" style={{ borderColor: "var(--line)" }}>
          <div>
            <h2 className="m-0 text-xl font-semibold tracking-tight">Your trial has all its agents</h2>
            <p className="mb-0 mt-1 text-sm" style={{ color: "var(--ink-3)" }}>
              Trial organizations can have {trialAgentLimit} {trialAgentLimit === 1 ? "agent" : "agents"}.
            </p>
          </div>
          <button type="button" aria-label="Close hiring dialog" className="af-btn af-btn-ghost af-btn-icon" onClick={onClose}><XIcon /></button>
        </header>
        <footer className="flex justify-end px-6 py-4">
          <button type="button" className="af-btn" onClick={onClose}>Close</button>
        </footer>
      </DialogShell>
    );
  }

  return (
    <DialogShell shadeClick={pending ? undefined : onClose}>
      <header className="flex items-start justify-between border-b px-6 py-5" style={{ borderColor: "var(--line)" }}>
        <div>
          <div className="mb-1 text-xs font-semibold uppercase tracking-[0.08em]" style={{ color: "var(--ink-3)" }}>New Agent</div>
          <h2 className="m-0 text-xl font-semibold tracking-tight">Hire a headless Agent</h2>
          <p className="mb-0 mt-1 text-sm" style={{ color: "var(--ink-3)" }}>Start with the runtime. Add a messaging platform or several connections afterward.</p>
        </div>
        <button type="button" aria-label="Close hiring dialog" className="af-btn af-btn-ghost af-btn-icon" disabled={pending} onClick={onClose}><XIcon /></button>
      </header>

      <div className="grid flex-1 gap-5 overflow-y-auto p-6 sm:grid-cols-2">
        {!createdAgent && (
          <>
        <FormField label="Agent name">
          <input aria-label="Agent name" className="af-input" value={name} maxLength={255} onChange={(event) => setManualName(event.target.value)} autoFocus />
          {suggestion.isLoading && <span role="status">Suggesting a name…</span>}
          {suggestion.error && (
            <span role="alert">
              Could not suggest a name. Enter one or{" "}
              <button type="button" onClick={() => void suggestion.retry()}>Retry name suggestion</button>.
            </span>
          )}
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
          <AgentErrorBanner
            failure={provisioningFailure}
            className="sm:col-span-2"
            testId="hire-provisioning-error"
          >
          </AgentErrorBanner>
        )}

        {error && (createdAgent || !template?.requiredSkills.length || skillCredentials.length === 0) && (
          <CredentialErrorAlert
            title={createdAgent ? "Could not start Agent" : "Could not hire Agent"}
            message={error}
          />
        )}
        {createdAgent && (provisioningFailure || error) && (
          <p className="m-0 text-sm sm:col-span-2">
            {createdAgent.name} was created and is waiting on your team page.
          </p>
        )}

      </div>

      <footer className="flex justify-end gap-2 border-t px-6 py-4" style={{ borderColor: "var(--line)" }}>
        <button type="button" className="af-btn" disabled={pending} onClick={onClose}>Cancel</button>
        <button type="button" className="af-btn af-btn-primary" disabled={pending || !canHire} onClick={() => void hire()}>
          {hireButtonLabel}
        </button>
      </footer>
    </DialogShell>
  );
}
