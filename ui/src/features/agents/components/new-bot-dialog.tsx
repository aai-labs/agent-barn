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

import { useHireAgentForm, type HiredAgent } from "../hooks/use-hire-agent-form";
import type { Agent } from "../schemas";
import { canAgent } from "../utils";
import { AgentErrorBanner } from "./agent-error-banner";
import { BotTrustNotice } from "./bot-trust-notice";
import { CredentialErrorAlert } from "./credential-error-alert";
import { DialogShell, FormField } from "./hire-dialog-primitives";
import { SkillsStep } from "./hire-dialog-steps";
import { ModelChoice } from "./model-choice";

export function NewBotDialog({
  parent,
  onClose,
  onAdded,
}: {
  parent: Agent;
  onClose: () => void;
  onAdded: (bot: HiredAgent) => void;
}) {
  const {
    templates,
    isLoadingTemplates: isLoading,
    template,
    templateKey,
    handleTemplateChange,
    name,
    setName,
    suggestion,
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
    pending,
    canHire,
    hire,
  } = useHireAgentForm({ onHired: onAdded, parent });

  const running = parent.status === "RUNNING";
  const restartBlocked = running && !canAgent(parent, "agent.lifecycle.manage");
  const parentIsManual = parent.approvalMode === "manual";

  return (
    <DialogShell shadeClick={pending ? undefined : onClose}>
      <header className="flex items-start justify-between border-b px-6 py-5" style={{ borderColor: "var(--line)" }}>
        <div>
          <div className="mb-1 text-xs font-semibold uppercase tracking-[0.08em]" style={{ color: "var(--ink-3)" }}>
            New bot in {parent.name}
          </div>
          <h2 className="m-0 text-xl font-semibold tracking-tight">Add a bot</h2>
          <p className="mb-0 mt-1 text-sm" style={{ color: "var(--ink-3)" }}>
            It runs inside {parent.name}&apos;s gateway. Chat with it on the web, then connect its own Slack or Telegram.
          </p>
        </div>
        <button
          type="button"
          aria-label="Close new bot dialog"
          className="af-btn af-btn-ghost af-btn-icon"
          disabled={pending}
          onClick={onClose}
        >
          <XIcon />
        </button>
      </header>

      <div className="grid flex-1 gap-5 overflow-y-auto p-6 sm:grid-cols-2">
        <FormField label="Bot name">
          <input
            aria-label="Bot name"
            className="af-input"
            value={name}
            maxLength={255}
            disabled={pending || suggestion.isLoading}
            onChange={(event) => setName(event.target.value)}
          />
        </FormField>
        <FormField label="Template" hint="The bot's own instructions, skills and identity.">
          <Select value={templateKey} onValueChange={handleTemplateChange} disabled={isLoading || pending}>
            <SelectTrigger aria-label="Template" className="w-full">
              <SelectValue placeholder={isLoading ? "Loading templates…" : "Choose a template"} />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {templates.map((item) => (
                  <SelectItem key={`${item.templateKey}:${item.version}`} value={item.templateKey}>
                    {item.templateName} · v{item.version}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </FormField>
        <FormField label="Model">
          <ModelChoice value={model} effectiveDefaultModel={defaultModel} onChange={setModel} disabled={pending} />
        </FormField>
        <FormField
          label="Command approval"
          hint={`Manual must be on for ${parent.name} and every bot in it, or none of them.`}
        >
          <Select
            value={approvalMode}
            onValueChange={(value) => setApprovalMode(value as "auto" | "off")}
            disabled={pending || parentIsManual}
          >
            <SelectTrigger aria-label="Command approval" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {parentIsManual ? (
                  <SelectItem value="manual">Manual</SelectItem>
                ) : (
                  <>
                    <SelectItem value="auto">Automatic</SelectItem>
                    <SelectItem value="off">Off</SelectItem>
                  </>
                )}
              </SelectGroup>
            </SelectContent>
          </Select>
        </FormField>

        {template && template.requiredSkills.length > 0 && (
          <section className="flex flex-col gap-3 border-t pt-5 sm:col-span-2" style={{ borderColor: "var(--line)" }}>
            <h3 className="m-0 text-base font-semibold" style={{ color: "var(--ink)" }}>
              Template skills and credentials
            </h3>
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

        <BotTrustNotice className="sm:col-span-2" />

        {running && (
          <p className="m-0 text-sm sm:col-span-2" style={{ color: "var(--ink-3)" }}>
            {restartBlocked
              ? `You need permission to restart ${parent.name}.`
              : `${parent.name} is running. Adding this bot restarts it and its other bots.`}
          </p>
        )}
        {provisioningFailure && (
          <AgentErrorBanner failure={provisioningFailure} className="sm:col-span-2" testId="new-bot-provisioning-error" />
        )}
        {error && (!template?.requiredSkills.length || skillCredentials.length === 0) && (
          <CredentialErrorAlert title="Could not add the bot" message={error} />
        )}
      </div>

      <footer className="flex justify-end gap-2 border-t px-6 py-4" style={{ borderColor: "var(--line)" }}>
        <button type="button" className="af-btn" disabled={pending} onClick={onClose}>
          Cancel
        </button>
        <button
          type="button"
          className="af-btn af-btn-primary"
          disabled={pending || !canHire || restartBlocked}
          onClick={() => void hire()}
        >
          {pending ? "Adding…" : running ? "Add & Restart" : "Add bot"}
        </button>
      </footer>
    </DialogShell>
  );
}
