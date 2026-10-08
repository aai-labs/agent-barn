"use client";

import { useMemo, useState } from "react";
import { Check, ChevronsUpDown, Loader2, RefreshCw } from "lucide-react";

import { ConfirmationDialog } from "@/components/confirmation-dialog";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import { formatDate } from "@/shared/date";
import { toastError } from "@/shared/toast";

import { useAgentApplyAndRestart } from "../hooks/use-agent-apply-and-restart";
import { useAgentTemplateSelectionOptions } from "../hooks/use-agent-template-selection-options";
import { useSelectAgentTemplate } from "../hooks/use-agent-override-actions";
import { useTemplates } from "../hooks/use-templates";
import {
  AgentConfigurationSection,
} from "./agent-configuration-section";
import { ConfigurationArtifactSurface } from "./configuration-artifact-surface";
import { ConfigurationRequiredSkills } from "./configuration-required-skills";
import { ConfigurationSnapshotMeta } from "./configuration-snapshot-meta";
import { canAgent, templateRequirementDelta } from "../utils";
import {
  templateSelectionValue,
  type TemplateSelectionOption,
} from "./agent-configuration-utils";
import type { Agent, AgentConfiguration } from "../schemas";

function optionKey(option: TemplateSelectionOption): string {
  return option.templateKey ?? "Agent-owned override";
}

export function AgentTemplateSelectionSettings({
  agent,
  configuration,
  canEdit,
}: {
  agent: Agent;
  configuration: AgentConfiguration;
  canEdit: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [applyConfirmOpen, setApplyConfirmOpen] = useState(false);
  const [selectedValue, setSelectedValue] = useState<string | null>(null);
  const [groupChoices, setGroupChoices] = useState<Record<string, string>>({});
  const selectTemplate = useSelectAgentTemplate();
  const { applyAndRestart, isPending: isRestartPending } = useAgentApplyAndRestart(agent);
  const {
    templates,
    isLoading: templatesLoading,
    error: templatesError,
  } = useTemplates({ pageSize: 100 });
  const { options, isLoading: versionsLoading, hasError: versionsError } =
    useAgentTemplateSelectionOptions({
      templates,
      active: configuration.active,
      overrideVersions: configuration.overrideVersions,
      sourceUpdate: configuration.sourceUpdate,
      sharedVersions: configuration.sharedVersions,
    });
  const active = configuration.active;
  const activeValue =
    active.pinType === "override"
      ? templateSelectionValue("override", undefined, active.version ?? undefined)
      : templateSelectionValue(
          active.sourceType,
          active.sourceTemplateKey,
          active.sourceTemplateVersion,
        );
  const selectedOption =
    options.find((option) => option.value === selectedValue) ??
    options.find((option) => option.value === activeValue) ??
    options[0];
  const isNoop = selectedOption?.value === activeValue;
  const requirements = useMemo(
    () =>
      templateRequirementDelta(
        selectedOption?.snapshot.requiredSkills ?? [],
        agent.skills,
      ),
    [agent.skills, selectedOption],
  );
  const chosenGroupMembers = requirements.pendingGroups.flatMap((group) => {
    const member = group.members.find((candidate) => candidate.id === groupChoices[group.key]);
    return member
      ? [{ skillId: member.id, name: member.name, version: member.version }]
      : [];
  });
  const awaitingGroupChoice =
    chosenGroupMembers.length < requirements.pendingGroups.length;
  const requiredAdditions = [...requirements.additions, ...chosenGroupMembers];
  const requiredPinChanges = requirements.pinChanges;
  const confirmedChanges = [
    ...requiredPinChanges.map(({ skillId, name, from, version }) => ({
      skillId,
      name,
      detail: `v${from} → v${version}`,
    })),
    ...requiredAdditions.map(({ skillId, name, version }) => ({
      skillId,
      name,
      detail: `added at v${version}`,
    })),
  ];
  const configuredProviders = new Set(
    (agent.secrets ?? []).map((secret) => secret.provider),
  );
  const requiredSkillsById = new Map(
    (selectedOption?.snapshot.requiredSkills ?? []).map((skill) => [skill.id, skill]),
  );
  const missingProviders = [
    ...new Set(
      [...requiredPinChanges, ...requiredAdditions].flatMap(
        (pin) =>
          requiredSkillsById
            .get(pin.skillId)
            ?.requiredProviders.filter((provider) => !configuredProviders.has(provider)) ?? [],
      ),
    ),
  ];
  const isRunning = agent.status === "RUNNING";
  const canApply = canEdit && (!isRunning || canAgent(agent, "agent.lifecycle.manage"));
  const isPending = selectTemplate.isPending || isRestartPending;
  const catalogLoading = templatesLoading || versionsLoading;
  const applyLabel = isRunning ? "Apply & Restart" : "Apply";

  async function applySelection() {
    if (
      !selectedOption ||
      !canApply ||
      isNoop ||
      awaitingGroupChoice ||
      missingProviders.length > 0 ||
      isPending
    ) {
      return;
    }

    try {
      await applyAndRestart(async (stoppedAgent) => {
        await selectTemplate.mutateAsync({
          agentId: stoppedAgent.id,
          selectionType: selectedOption.selectionType,
          templateKey: selectedOption.templateKey,
          templateVersion: selectedOption.templateVersion,
          overrideVersion: selectedOption.overrideVersion,
          expectedAgentUpdatedAt: stoppedAgent.updatedAt,
          ...(requiredAdditions.length > 0
            ? { skillIds: requiredAdditions.map(({ skillId }) => skillId) }
            : {}),
          ...(requiredPinChanges.length > 0 || requiredAdditions.length > 0
            ? {
                skillVersions: [...requiredPinChanges, ...requiredAdditions].map(
                  ({ skillId, version }) => ({ skillId, version }),
                ),
              }
            : {}),
        });
      });
      setApplyConfirmOpen(false);
    } catch (error) {
      toastError(error);
    }
  }

  function requestApply() {
    if (
      !selectedOption ||
      !canApply ||
      isNoop ||
      awaitingGroupChoice ||
      missingProviders.length > 0 ||
      isPending
    ) {
      return;
    }
    setApplyConfirmOpen(true);
  }

  return (
    <AgentConfigurationSection
      title="Template selection"
      description={
        isRunning
          ? "Choose any published shared or Agent-owned version. Applying it restarts the Agent with the selected configuration."
          : "Choose any published shared or Agent-owned version. Applying it updates the pin and keeps the Agent stopped until you start it from the Agent detail page."
      }
      footer={
        <button
          type="button"
          className="af-btn af-btn-primary"
          disabled={
            !selectedOption ||
            !canApply ||
            isNoop ||
            awaitingGroupChoice ||
            missingProviders.length > 0 ||
            catalogLoading ||
            isPending
          }
          onClick={requestApply}
        >
          {isPending && <Loader2 size={14} className="animate-spin" />}
          {isPending ? (isRunning ? "Applying & Restarting…" : "Applying…") : applyLabel}
        </button>
      }
    >
      <div className="flex flex-col gap-5">
        <div className="flex flex-col gap-3">
          <div className="min-w-0">
            <label
              htmlFor="agent-template-version"
              className="mb-2 block text-[0.78rem] font-semibold uppercase tracking-[0.08em]"
              style={{ color: "var(--ink-4)" }}
            >
              Template version
            </label>
            <Popover open={open} onOpenChange={setOpen}>
              <PopoverTrigger asChild>
                <Button
                  id="agent-template-version"
                  type="button"
                  variant="outline"
                  role="combobox"
                  aria-label="Template version"
                  aria-expanded={open}
                  aria-haspopup="listbox"
                  disabled={options.length === 0}
                  className="h-auto min-h-9 w-full justify-between gap-3 py-2 text-left"
                >
                  {selectedOption ? (
                    <span className="min-w-0 flex-1">
                      <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5">
                        <span className="truncate font-medium">
                          {selectedOption.name}
                        </span>
                        <span className="text-muted-foreground">
                          v{selectedOption.version}
                        </span>
                        <span className="text-muted-foreground">
                          · {selectedOption.typeLabel}
                        </span>
                        {selectedOption.value === activeValue && (
                          <span
                            className="rounded-full px-1.5 py-0.5 text-[0.68rem] font-medium"
                            style={{
                              background: "color-mix(in srgb, var(--ok) 14%, transparent)",
                              color: "var(--ok)",
                            }}
                          >
                            Active
                          </span>
                        )}
                      </span>
                      <span className="block truncate text-xs text-muted-foreground">
                        Template key: {optionKey(selectedOption)}
                        {selectedOption.isLatest ? " · Latest" : ""}
                      </span>
                    </span>
                  ) : (
                    <span className="text-muted-foreground">Select a template version</span>
                  )}
                  <ChevronsUpDown data-icon="inline-end" className="shrink-0 opacity-50" />
                </Button>
              </PopoverTrigger>
              <PopoverContent
                align="start"
                className="w-[min(42rem,calc(100vw-2rem))] p-0"
              >
                <Command>
                  <CommandInput placeholder="Search templates, versions, or keys..." />
                  <CommandList>
                    <CommandEmpty>No template versions found.</CommandEmpty>
                    <CommandGroup heading="Published versions">
                      {options.map((option) => {
                        const isActive = option.value === activeValue;
                        return (
                          <CommandItem
                            key={option.value}
                            value={option.searchText}
                            onSelect={() => {
                              setSelectedValue(option.value);
                              setGroupChoices({});
                              setOpen(false);
                            }}
                            className="items-start py-2.5"
                          >
                          <Check
                            aria-hidden
                            className={cn(
                              "mt-0.5 opacity-0",
                              option.value === selectedOption?.value && "opacity-100",
                            )}
                          />
                          <span className="min-w-0 flex-1">
                            <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5">
                              <span className="truncate font-medium">
                                {option.name}
                              </span>
                              <span className="text-muted-foreground">
                                v{option.version}
                              </span>
                              <span className="rounded-full bg-muted px-1.5 py-0.5 text-[0.68rem] font-medium text-muted-foreground">
                                {option.typeLabel}
                              </span>
                              {option.isLatest && (
                                <span className="rounded-full bg-primary/10 px-1.5 py-0.5 text-[0.68rem] font-medium text-primary">
                                  Latest
                                </span>
                              )}
                              {isActive && (
                                <span
                                  className="rounded-full px-1.5 py-0.5 text-[0.68rem] font-medium"
                                  style={{
                                    background: "color-mix(in srgb, var(--ok) 14%, transparent)",
                                    color: "var(--ok)",
                                  }}
                                >
                                  Active
                                </span>
                              )}
                              {option.platformUpdateAvailable && (
                                <span className="rounded-full bg-amber-500/10 px-1.5 py-0.5 text-[0.68rem] font-medium text-amber-700 dark:text-amber-300">
                                  Platform update
                                </span>
                              )}
                              {option.sourceUpdateAvailable && (
                                <span className="rounded-full bg-amber-500/10 px-1.5 py-0.5 text-[0.68rem] font-medium text-amber-700 dark:text-amber-300">
                                  {option.selectionType === "platform" ? "Platform update" : "Organization update"}
                                </span>
                              )}
                            </span>
                            <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                              Template key: {optionKey(option)}
                              {option.snapshot.description
                                ? ` · ${option.snapshot.description}`
                                : ""}
                            </span>
                            <span className="mt-0.5 block text-[0.68rem] text-muted-foreground">
                              Updated {formatDate(option.updatedAt)}
                            </span>
                          </span>
                          </CommandItem>
                        );
                      })}
                    </CommandGroup>
                  </CommandList>
                </Command>
              </PopoverContent>
            </Popover>
            {catalogLoading && (
              <p className="mb-0 mt-2 text-xs text-muted-foreground">
                Loading the available template versions...
              </p>
            )}
            {(templatesError || versionsError) && (
              <p className="mb-0 mt-2 text-xs text-destructive">
                Some template versions could not be loaded. The available versions are still shown.
              </p>
            )}
            {configuration.sourceUpdate && (
              <p className="mb-0 mt-2 text-xs text-muted-foreground">
                A newer {configuration.sourceUpdate.sourceType === "platform" ? "Platform" : "Organization"} source version (v{configuration.sourceUpdate.sourceTemplateVersion}) is available. Selecting it repins the Agent and leaves any existing Override Draft unchanged.
              </p>
            )}
          </div>
        </div>

        {!canApply && (
          <p className="mb-0 text-xs text-muted-foreground">
            Applying a version requires Agent edit permission{isRunning ? " and lifecycle permission" : ""}.
          </p>
        )}

        {selectedOption && (
          <div className="rounded-xl border bg-muted/20 p-4">
            <div className="mb-4">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="m-0 text-[0.95rem] font-semibold">
                  {selectedOption.name} · v{selectedOption.version}
                </h3>
                <span className="rounded-full bg-muted px-1.5 py-0.5 text-[0.68rem] font-medium text-muted-foreground">
                  {selectedOption.typeLabel}
                </span>
                {selectedOption.isLatest && (
                  <span className="rounded-full bg-primary/10 px-1.5 py-0.5 text-[0.68rem] font-medium text-primary">
                    Latest
                  </span>
                )}
                {selectedOption.sourceUpdateAvailable && (
                  <span className="rounded-full bg-amber-500/10 px-1.5 py-0.5 text-[0.68rem] font-medium text-amber-700 dark:text-amber-300">
                    {selectedOption.selectionType === "platform" ? "Platform update" : "Organization update"}
                  </span>
                )}
                {selectedOption.value === activeValue && (
                  <span
                    className="rounded-full px-1.5 py-0.5 text-[0.68rem] font-medium"
                    style={{
                      background: "color-mix(in srgb, var(--ok) 14%, transparent)",
                      color: "var(--ok)",
                    }}
                  >
                    Active
                  </span>
                )}
              </div>
              <ConfigurationSnapshotMeta snapshot={selectedOption.snapshot} />
              <p className="mb-0 mt-2 text-[0.84rem] text-muted-foreground">
                {selectedOption.snapshot.description || "No description"}
              </p>
            </div>
            <ConfigurationArtifactSurface snapshot={selectedOption.snapshot} />
            <ConfigurationRequiredSkills snapshot={selectedOption.snapshot} />
            {requirements.pendingGroups.map((group) => (
              <div key={group.key} className="mt-4">
                <div
                  className="mb-2 text-[0.75rem] font-semibold uppercase tracking-[0.08em]"
                  style={{ color: "var(--ink-4)" }}
                >
                  Choose one of {group.key}
                </div>
                <div className="flex flex-wrap gap-2" role="radiogroup" aria-label={`Choose one of ${group.key}`}>
                  {group.members.map((member) => {
                    const chosen = groupChoices[group.key] === member.id;
                    return (
                      <button
                        key={member.id}
                        type="button"
                        role="radio"
                        aria-checked={chosen}
                        className={cn("af-btn af-btn-sm", chosen ? "af-btn-primary" : "af-btn-ghost")}
                        onClick={() =>
                          setGroupChoices((previous) => ({
                            ...previous,
                            [group.key]: member.id,
                          }))
                        }
                      >
                        {member.name} v{member.version}
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
            {requiredAdditions.length > 0 && (
              <p className="mb-0 mt-4 text-xs text-muted-foreground">
                Applying adds{" "}
                {requiredAdditions
                  .map((addition) => `${addition.name} v${addition.version}`)
                  .join(", ")}{" "}
                to this Agent.
              </p>
            )}
            {missingProviders.length > 0 && (
              <p className="mb-0 mt-2 text-xs text-destructive">
                These skills need credentials that are not configured:{" "}
                {missingProviders.join(", ")}. Add them in the Keys section first.
              </p>
            )}
          </div>
        )}
      </div>
      <ConfirmationDialog
        open={applyConfirmOpen}
        onOpenChange={setApplyConfirmOpen}
        title={isRunning ? "Apply this version and restart the Agent?" : "Apply this version?"}
        description={
          selectedOption
            ? isRunning
              ? `This will pin ${selectedOption.name} v${selectedOption.version} to ${agent.name}, stop the Agent, and start it again with the selected configuration.`
              : `This will pin ${selectedOption.name} v${selectedOption.version} to ${agent.name} and keep the Agent stopped. Start it from the Agent detail page when you are ready.`
            : isRunning
              ? "The Agent will restart with the selected template version."
              : "The selected template version will be applied while the Agent remains stopped."
        }
        confirmLabel={applyLabel}
        pendingLabel={isRunning ? "Applying & Restarting…" : "Applying…"}
        onConfirm={() => void applySelection()}
        isPending={isPending}
        icon={<RefreshCw size={18} />}
      >
        {confirmedChanges.length > 0 && (
          <div className="rounded-lg border p-3">
            <p className="mb-2 mt-0 text-xs font-semibold">
              This will also update the skills required by this template:
            </p>
            <ul className="m-0 flex list-none flex-col gap-1 p-0">
              {confirmedChanges.map((change) => (
                <li
                  key={change.skillId}
                  className="flex flex-wrap items-center justify-between gap-2 text-xs"
                >
                  <span>{change.name}</span>
                  <span className="font-mono text-muted-foreground">{change.detail}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </ConfirmationDialog>
    </AgentConfigurationSection>
  );
}
