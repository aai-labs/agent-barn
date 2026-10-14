"use client";

import { useState } from "react";
import { ArrowLeft, ArrowRight } from "lucide-react";

import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { AgentErrorBanner } from "@/features/agents/components/agent-error-banner";
import { CredentialErrorAlert } from "@/features/agents/components/credential-error-alert";
import { FormField } from "@/features/agents/components/hire-dialog-primitives";
import { SkillsStep } from "@/features/agents/components/hire-dialog-steps";
import { ModelChoice } from "@/features/agents/components/model-choice";
import { RuntimeChoice } from "@/features/agents/components/runtime-choice";
import { useHireAgentForm, type HiredAgent } from "@/features/agents/hooks/use-hire-agent-form";

import { OnboardingShell, StepAlert } from "./onboarding-shell";

const TEMPLATES_PER_PAGE = 6;

/** Step 3 of "build my own": the hire dialog's choices, laid out as a wizard step. */
export function SetupStep({
  email,
  creditUsd,
  onBack,
  onHired,
  onLater,
}: {
  email: string;
  creditUsd: number | null;
  onBack: () => void;
  onHired: (agent: HiredAgent) => void;
  onLater: () => void;
}) {
  const form = useHireAgentForm({ onHired });
  const { template, createdAgent, pending, error, provisioningFailure } = form;
  const [templatePage, setTemplatePage] = useState(0);
  const pageCount = Math.ceil(form.templates.length / TEMPLATES_PER_PAGE);
  const currentPage = Math.min(templatePage, Math.max(0, pageCount - 1));
  const pageStart = currentPage * TEMPLATES_PER_PAGE;
  const visibleTemplates = form.templates.slice(pageStart, pageStart + TEMPLATES_PER_PAGE);

  const hireLabel = createdAgent ? (pending ? "Starting…" : "Start again") : pending ? "Hiring…" : "Hire agent";

  return (
    <OnboardingShell
      step={2}
      path="own"
      email={email}
      creditUsd={creditUsd}
      title="Set up your agent"
      subtitle="You can change all of this later in its settings. Channels are added after it's hired."
      footerStart={
        <button type="button" className="af-btn af-btn-ghost af-btn-lg" disabled={pending || !!createdAgent} onClick={onBack}>
          <ArrowLeft aria-hidden />
          Back
        </button>
      }
      footerEnd={
        <>
          <button type="button" className="af-btn af-btn-ghost" disabled={pending} onClick={onLater}>
            I&apos;ll do this later
          </button>
          <button
            type="button"
            className="af-btn af-btn-primary af-btn-lg"
            disabled={pending || !form.canHire}
            onClick={() => void form.hire()}
          >
            {hireLabel}
            {!pending && !createdAgent && <ArrowRight aria-hidden />}
          </button>
        </>
      }
    >
      {form.templatesError && <div className="mb-4"><StepAlert>We couldn&apos;t load templates.</StepAlert><button type="button" className="af-btn mt-2" onClick={() => void form.reloadTemplates()}>Try again</button></div>}
      {!form.isLoadingTemplates && !form.templatesError && !form.templates.length && <p>No templates are available yet. Ask your administrator to publish one.</p>}
      <fieldset disabled={pending} className="m-0 grid max-w-[640px] gap-5 border-0 p-0 sm:grid-cols-2">
        {!createdAgent && (
          <>
            <FormField label="Agent name">
              <input
                aria-label="Agent name"
                className="af-input"
                value={form.name}
                maxLength={255}
                onChange={(event) => form.setName(event.target.value)}
              />
              {form.suggestion.isLoading && <span role="status">Suggesting a name…</span>}
              {form.suggestion.error && (
                <span role="alert">
                  Could not suggest a name. Enter one or{" "}
                  <button type="button" onClick={() => void form.suggestion.retry()}>
                    Retry name suggestion
                  </button>
                  .
                </span>
              )}
            </FormField>
            <FormField label="Runtime">
              <RuntimeChoice value={form.agentType} onChange={form.setAgentType} disabled={pending} />
            </FormField>
            <div className="sm:col-span-2">
              <FormField label="Template">
                {form.isLoadingTemplates ? (
                  <span role="status" className="text-[13px]" style={{ color: "var(--ink-3)" }}>
                    Loading templates…
                  </span>
                ) : (
                  <>
                    <div role="radiogroup" aria-label="Template" className="grid gap-2 p-[3px] sm:grid-cols-2">
                      {visibleTemplates.map((item) => {
                        const selected = item.templateKey === form.templateKey;
                        return (
                          <button
                            key={`${item.templateKey}:${item.version}`}
                            type="button"
                            role="radio"
                            aria-checked={selected}
                            className="af-hover-bg flex items-start gap-2.5 rounded-[10px] border px-3 py-2.5 text-left"
                            style={{
                              borderColor: selected ? "var(--ink)" : "var(--line-strong)",
                              boxShadow: selected ? "0 0 0 3px var(--bg-sunken)" : undefined,
                            }}
                            onClick={() => form.handleTemplateChange(item.templateKey)}
                          >
                            <span
                              aria-hidden
                              className="grid size-7 shrink-0 place-items-center rounded-lg text-[12px] font-semibold"
                              style={{ background: "var(--ink)", color: "var(--bg-elev)" }}
                            >
                              {item.templateName.charAt(0)}
                            </span>
                            <span className="min-w-0">
                              <span className="block text-[13px] font-semibold" style={{ color: "var(--ink)" }}>
                                {item.templateName}
                              </span>
                              {item.description && (
                                <span className="line-clamp-2 text-[12px]" style={{ color: "var(--ink-3)" }}>
                                  {item.description}
                                </span>
                              )}
                            </span>
                          </button>
                        );
                      })}
                    </div>
                    {pageCount > 1 && (
                      <nav aria-label="Template pages" className="mt-3 flex flex-wrap items-center justify-between gap-2 text-[12px]" style={{ color: "var(--ink-3)" }}>
                        <span aria-live="polite" aria-atomic="true">
                          {pageStart + 1}–{Math.min(pageStart + TEMPLATES_PER_PAGE, form.templates.length)} of {form.templates.length} templates
                        </span>
                        <div className="flex gap-1">
                          <button type="button" aria-label="Previous templates" className="af-btn af-btn-ghost" disabled={currentPage === 0} onClick={() => setTemplatePage(currentPage - 1)}>
                            <ArrowLeft size={14} aria-hidden /> Previous
                          </button>
                          <button type="button" aria-label="Next templates" className="af-btn af-btn-ghost" disabled={currentPage + 1 >= pageCount} onClick={() => setTemplatePage(currentPage + 1)}>
                            Next <ArrowRight size={14} aria-hidden />
                          </button>
                        </div>
                      </nav>
                    )}
                    {template && pageCount > 1 && (
                      <p className="mb-0 mt-2 text-[12px]" style={{ color: "var(--ink-3)" }}>Selected: {template.templateName}</p>
                    )}
                  </>
                )}
              </FormField>
            </div>
            <FormField label="Model">
              <ModelChoice
                value={form.model}
                effectiveDefaultModel={form.defaultModel}
                onChange={form.setModel}
                disabled={pending}
              />
            </FormField>
            {form.agentType === "hermes" && (
              <FormField label="Command approval">
                <Select
                  value={form.approvalMode}
                  onValueChange={(value) => form.setApprovalMode(value as "manual" | "auto" | "off")}
                  disabled={pending}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      <SelectItem value="auto">Automatic</SelectItem>
                      <SelectItem value="manual">Manual</SelectItem>
                      <SelectItem value="off">Off</SelectItem>
                    </SelectGroup>
                  </SelectContent>
                </Select>
              </FormField>
            )}

            {template && template.requiredSkills.length > 0 && (
              <section className="flex flex-col gap-3 border-t pt-5 sm:col-span-2" style={{ borderColor: "var(--line)" }}>
                <div>
                  <h3 className="m-0 text-base font-semibold" style={{ color: "var(--ink)" }}>
                    Template skills and credentials
                  </h3>
                  <p className="mb-0 mt-1 text-sm" style={{ color: "var(--ink-3)" }}>
                    This template needs these skills. Their credentials are checked before your agent is created.
                  </p>
                </div>
                <SkillsStep
                  key={`${template.templateKey}:${template.version}`}
                  selectedSkillIds={form.selectedSkillIds}
                  skillCredentials={form.skillCredentials}
                  onSkillIdsChange={form.setSelectedSkillIds}
                  onSkillCredentialsChange={form.setSkillCredentials}
                  templateRequiredSkills={form.standalone}
                  requiredGroups={form.groups}
                  groupChoices={form.groupChoices}
                  onGroupChoiceChange={form.handleGroupChoiceChange}
                  credentialError={error}
                />
              </section>
            )}
          </>
        )}

        {provisioningFailure && (
          <AgentErrorBanner failure={provisioningFailure} className="sm:col-span-2" testId="hire-provisioning-error" />
        )}
        {error && (createdAgent || !template?.requiredSkills.length || form.skillCredentials.length === 0) && (
          <div className="sm:col-span-2">
            <CredentialErrorAlert title={createdAgent ? "Could not start your agent" : "Could not hire your agent"} message={error} />
          </div>
        )}
        {createdAgent && (provisioningFailure || error) && (
          <p className="m-0 text-sm sm:col-span-2">
            {createdAgent.name} was created but didn&apos;t start. Start it again, or find it on your dashboard.
          </p>
        )}

      </fieldset>
    </OnboardingShell>
  );
}
