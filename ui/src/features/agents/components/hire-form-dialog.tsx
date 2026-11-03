"use client";

import { XIcon } from "@/components/icons";
import { AgentSizeSelect } from "@/features/agent-sizes/components/agent-size-select";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { useSyncProvidersQuery } from "@/features/sync-provider/hooks/use-sync-providers-query";
import { FILE_SYNC } from "@/features/sync-provider/schemas";
import { useHireAgentForm, type HiredAgent } from "../hooks/use-hire-agent-form";
import { CredentialErrorAlert } from "./credential-error-alert";
import { AgentErrorBanner } from "./agent-error-banner";
import { DialogShell, FormField } from "./hire-dialog-primitives";
import { SkillsStep } from "./hire-dialog-steps";
import { ModelChoice } from "./model-choice";
import { RuntimeChoice } from "./runtime-choice";

interface HireDialogProps {
  onClose: () => void;
  onHired: (agent: HiredAgent) => void;
}

export function HireFormDialog({ onClose, onHired }: HireDialogProps) {
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
    fileSyncEnabled,
    setFileSyncEnabled,
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
  } = useHireAgentForm({ onHired });
  const { providers } = useSyncProvidersQuery();
  const fileSyncProvider = providers?.find(
    (provider) => provider.connection?.status === "active" && provider.capabilities.includes(FILE_SYNC),
  );
  const fieldsBeforeHint = 4 + (agentType === "hermes" ? 1 : 0) + (fileSyncProvider ? 1 : 0);
  const hintStartsRow = fieldsBeforeHint % 2 === 0;

  const hireButtonLabel = createdAgent
    ? pending
      ? "Starting…"
      : "Start again"
    : pending
      ? "Hiring…"
      : "Hire Agent";

  return (
    <DialogShell shadeClick={pending ? undefined : onClose}>
      <header className="flex items-start justify-between border-b px-6 py-5" style={{ borderColor: "var(--line)" }}>
        <div>
          <div className="mb-1 text-xs font-semibold uppercase tracking-[0.08em]" style={{ color: "var(--ink-3)" }}>New Agent</div>
          <h2 className="m-0 text-xl font-semibold tracking-tight">Build your own agent</h2>
          <p className="mb-0 mt-1 text-sm" style={{ color: "var(--ink-3)" }}>Choose a template, runtime and model. Start chatting on the web and add more channels later.</p>
        </div>
        <button type="button" aria-label="Close hiring dialog" className="af-btn af-btn-ghost af-btn-icon" disabled={pending} onClick={onClose}><XIcon /></button>
      </header>

      <div className="grid flex-1 gap-5 overflow-y-auto p-6 sm:grid-cols-2">
        {!createdAgent && (
          <>
        <FormField label="Agent name">
          <input aria-label="Agent name" className="af-input" value={name} maxLength={255} disabled={pending || suggestion.isLoading} onChange={(event) => setManualName(event.target.value)} autoFocus />
          {suggestion.isLoading && <span role="status">Suggesting a name…</span>}
          {suggestion.error && (
            <span role="alert">
              Could not suggest a name. Enter one or{" "}
              <button type="button" onClick={() => void suggestion.retry()}>Retry name suggestion</button>.
            </span>
          )}
        </FormField>
        <FormField label="Runtime">
          <RuntimeChoice value={agentType} onChange={setAgentType} disabled={pending} />
        </FormField>
        {sizeChoices && (
          <FormField label="CPU & memory" hint="You can change it later; a change applies when the agent restarts.">
            <AgentSizeSelect
              sizes={sizeChoices}
              value={agentSizeId ?? sizeChoices.find((size) => size.isDefault)?.id ?? ""}
              onChange={(size) => setAgentSizeId(size.isDefault ? null : size.id)}
              disabled={pending}
            />
          </FormField>
        )}
        <FormField label="Template" hint="Communication connections do not belong to templates or runtimes.">
          <Select value={templateKey} onValueChange={handleTemplateChange} disabled={isLoading || pending}>
            <SelectTrigger aria-label="Template" className="w-full"><SelectValue placeholder={isLoading ? "Loading templates…" : "Choose a template"} /></SelectTrigger>
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
            <SelectTrigger aria-label="Command approval" className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent><SelectGroup><SelectItem value="auto">Automatic</SelectItem><SelectItem value="manual">Manual</SelectItem><SelectItem value="off">Off</SelectItem></SelectGroup></SelectContent>
            </Select>
          </FormField>
        )}
        {fileSyncProvider && (
          <div className="flex items-center justify-between gap-4">
            <span id="hire-file-sync-label" className="text-[0.84rem] font-medium" style={{ color: "var(--ink)" }}>
              Sync files with {fileSyncProvider.displayName}
            </span>
            <button
              type="button"
              role="switch"
              aria-labelledby="hire-file-sync-label"
              aria-checked={fileSyncEnabled}
              disabled={pending}
              onClick={() => setFileSyncEnabled(!fileSyncEnabled)}
              className="relative h-5 w-9 shrink-0 rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-50"
              style={{ backgroundColor: fileSyncEnabled ? "var(--ink)" : "var(--line)" }}
            >
              <span
                className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white transition-transform ${fileSyncEnabled ? "translate-x-4" : ""}`}
              />
            </button>
          </div>
        )}
        <div className={cn("rounded-xl border border-dashed p-4 text-sm", hintStartsRow && "sm:col-span-2")} style={{ color: "var(--ink-3)" }}>
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
