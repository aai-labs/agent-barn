"use client";

import { forwardRef, useEffect, useImperativeHandle, useState } from "react";
import Link from "next/link";
import { useDebouncedValue } from "@tanstack/react-pacer";
import { Loader2, Plus, Trash2 } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { Badge } from "@/components/badge";
import { ConfirmationDialog } from "@/components/confirmation-dialog";
import { SearchIcon } from "@/components/icons";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { SharedManualToggle } from "@/features/shared-credentials/components/shared-manual-toggle";
import { useSharedManualSwitch } from "@/features/shared-credentials/hooks/use-shared-manual-switch";
import { SHARED_CREDENTIAL_PROVIDER_LABELS } from "@/features/shared-credentials/utils";
import { useInfiniteSkills } from "@/features/skills/hooks/use-skills";
import { useSkillVersions } from "@/features/skills/hooks/use-skill-versions";
import { SKILL_PROVIDER_LABELS } from "@/features/skills/utils";
import { skillDetailHref, skillNewHref, type SkillScopeRef } from "@/features/skills/scope";
import { SkillCard } from "@/features/skills/components/skill-card";
import { useLoadMoreOnScroll } from "@/hooks/use-load-more-on-scroll";
import type { Skill } from "@/features/skills/schemas";

import {
  coerceBooleanFields,
  expandGithubContent,
  getIntegrationProvider,
  hasIncompleteIntegration,
  type IntegrationDraft,
} from "../integrations";
import { useUpdateAgent } from "../hooks/use-update-agent";
import type { Agent, AgentAssignedSkill } from "../schemas";
import type { AgentConfigurationEditHandle } from "./agent-configuration-utils";
import { CredentialErrorAlert } from "./credential-error-alert";
import { IntegrationFields } from "./integration-fields";

interface AgentSkillsTabProps {
  agent: Agent;
  isRunning: boolean;
  onDirtyChange?: (isDirty: boolean, isValid?: boolean) => void;
}

export const AgentSkillsTab = forwardRef<
  AgentConfigurationEditHandle,
  AgentSkillsTabProps
>(function AgentSkillsTab({ agent, isRunning, onDirtyChange }, ref) {
  const scope: SkillScopeRef = { kind: "agent", agentId: agent.id };
  const [search, setSearch] = useState("");
  const [debouncedSearch] = useDebouncedValue(search, { wait: 300 });
  const {
    skills,
    isLoading,
    error,
    refetch,
    hasNextPage,
    fetchNextPage,
    isFetchingNextPage,
    isFetchingNextPageError,
  } = useInfiniteSkills({
    scope,
    search: debouncedSearch || undefined,
  });
  const loadMoreRef = useLoadMoreOnScroll({
    hasNextPage: Boolean(hasNextPage),
    isFetchingNextPage,
    fetchNextPage: () => void fetchNextPage(),
  });
  const updateAgent = useUpdateAgent();

  const [pendingAddIds, setPendingAddIds] = useState<string[]>([]);
  const [pendingAddSkills, setPendingAddSkills] = useState<Skill[]>([]);
  const [pendingRemoveIds, setPendingRemoveIds] = useState<string[]>([]);
  const [pendingPins, setPendingPins] = useState<Record<string, number>>({});
  const [newSecretDrafts, setNewSecretDrafts] = useState<IntegrationDraft[]>([]);
  const [skillToRemove, setSkillToRemove] = useState<AgentAssignedSkill | null>(null);

  const existingSecretProviders = new Set(
    (agent.secrets ?? []).map((s) => s.provider),
  );

  const currentSkills = agent.skills.filter(
    (s) => !pendingRemoveIds.includes(s.id),
  );

  const assignedIds = new Set(agent.skills.map((s) => s.id));
  const availableSkills = skills.filter(
    (s) => !assignedIds.has(s.id) && !pendingAddIds.includes(s.id),
  );

  const newlyRequiredProviderIds = [
    ...new Set(
      pendingAddSkills
        .flatMap((s) => s.requiredProviders)
        .filter((p) => !existingSecretProviders.has(p)),
    ),
  ];

  const pendingPinChanges = Object.entries(pendingPins).filter(([skillId, version]) =>
    agent.skills.some((skill) => skill.id === skillId && skill.version !== version),
  );
  const hasPendingChanges =
    pendingAddIds.length > 0 || pendingRemoveIds.length > 0 || pendingPinChanges.length > 0;
  const isValid = !hasIncompleteIntegration(newSecretDrafts);
  const credentialError = updateAgent.error instanceof Error
    ? updateAgent.error.message
    : updateAgent.error
      ? "Save failed"
      : null;

  useEffect(() => {
    onDirtyChange?.(hasPendingChanges || newSecretDrafts.length > 0, isValid);
  }, [hasPendingChanges, isValid, newSecretDrafts.length, onDirtyChange]);

  function addSkill(skill: Skill) {
    const needed = skill.requiredProviders.filter(
      (p) => !existingSecretProviders.has(p),
    );
    setPendingAddIds((prev) => (prev.includes(skill.id) ? prev : [...prev, skill.id]));
    setPendingAddSkills((prev) => (prev.some((item) => item.id === skill.id) ? prev : [...prev, skill]));
    setNewSecretDrafts((prev) => {
      const existing = new Set(prev.map((d) => d.provider));
      const toAdd = needed.filter((p) => !existing.has(p));
      return [...prev, ...toAdd.map((p) => ({ provider: p, content: {} }))];
    });
  }

  function cancelAdd(skillId: string) {
    const remaining = pendingAddSkills.filter((s) => s.id !== skillId);
    const stillNeeded = new Set(
      remaining
        .flatMap((s) => s.requiredProviders)
        .filter((p) => !existingSecretProviders.has(p)),
    );
    setPendingAddIds((prev) => prev.filter((id) => id !== skillId));
    setPendingAddSkills(remaining);
    setNewSecretDrafts((prev) =>
      prev.filter((d) => stillNeeded.has(d.provider)),
    );
  }

  function markForRemoval(skillId: string) {
    setPendingRemoveIds((prev) => [...prev, skillId]);
    setPendingPins((prev) => {
      const next = { ...prev };
      delete next[skillId];
      return next;
    });
  }

  function confirmRemoval() {
    if (!skillToRemove) return;
    markForRemoval(skillToRemove.id);
    setSkillToRemove(null);
  }

  function undoRemoval(skillId: string) {
    setPendingRemoveIds((prev) => prev.filter((id) => id !== skillId));
  }

  function setField(provider: string, key: string, value: string) {
    setNewSecretDrafts((prev) =>
      prev.map((d) =>
        d.provider === provider
          ? { ...d, content: { ...d.content, [key]: value } }
          : d,
      ),
    );
  }

  function setRepos(provider: string, key: string, repos: string[]) {
    setNewSecretDrafts((prev) =>
      prev.map((d) =>
        d.provider === provider
          ? { ...d, content: { ...d.content, [key]: repos } }
          : d,
      ),
    );
  }

  /** Apply several keys at once — the OAuth flow writes its whole result together. */
  function setFields(provider: string, patch: Record<string, string | string[]>) {
    setNewSecretDrafts((prev) =>
      prev.map((d) =>
        d.provider === provider
          ? { ...d, content: { ...d.content, ...patch } }
          : d,
      ),
    );
  }

  const { switchToShared, switchToManual, handlePickShared } = useSharedManualSwitch(
    newSecretDrafts,
    setNewSecretDrafts,
  );

  async function handleSave() {
    if (hasIncompleteIntegration(newSecretDrafts)) return;
    updateAgent.reset();
    // Providers required by skills that survive this update (kept + newly added).
    const survivingSkills = [
      ...agent.skills.filter((s) => !pendingRemoveIds.includes(s.id)),
      ...pendingAddSkills,
    ];
    const stillNeeded = new Set(survivingSkills.flatMap((s) => s.requiredProviders));

    // Secrets whose provider is no longer required by any remaining skill.
    const orphanedProviders = [
      ...new Set(
        agent.skills
          .filter((s) => pendingRemoveIds.includes(s.id))
          .flatMap((s) => s.requiredProviders)
          .filter((p) => !stillNeeded.has(p)),
      ),
    ];

    const manualDrafts = newSecretDrafts.filter((d) => !d.sharedCredentialId);
    const sharedDrafts = newSecretDrafts.filter((d) => !!d.sharedCredentialId);

    await updateAgent.mutateAsync({
      agentId: agent.id,
      skillIds: pendingAddIds,
      removedSkillIds: pendingRemoveIds,
      ...(pendingPinChanges.length > 0
        ? {
            skillVersions: pendingPinChanges
              .filter(([skillId]) => !pendingRemoveIds.includes(skillId))
              .map(([skillId, version]) => ({ skillId, version })),
          }
        : {}),
      ...(orphanedProviders.length > 0 ? { removedSecretProviders: orphanedProviders } : {}),
      ...(manualDrafts.length > 0
        ? {
            secrets: manualDrafts.map((d) => ({
              provider: d.provider,
              content: coerceBooleanFields(d.provider === "github" ? expandGithubContent(d.content) : d.content),
            })),
          }
        : {}),
      ...(sharedDrafts.length > 0
        ? { sharedCredentials: sharedDrafts.map((d) => ({ sharedCredentialId: d.sharedCredentialId! })) }
        : {}),
    });
    setPendingAddIds([]);
    setPendingAddSkills([]);
    setPendingRemoveIds([]);
    setPendingPins({});
    setNewSecretDrafts([]);
  }

  function resetForm() {
    setPendingAddIds([]);
    setPendingAddSkills([]);
    setPendingRemoveIds([]);
    setPendingPins({});
    setNewSecretDrafts([]);
    updateAgent.reset();
  }

  useImperativeHandle(ref, () => ({ apply: handleSave, cancel: resetForm }));

  if (isLoading) {
    return (
      <div className="flex flex-col gap-2 animate-pulse">
        {Array.from({ length: 3 }).map((_, i) => (
          <div
            key={i}
            className="h-10 rounded-xl"
            style={{ background: "var(--bg-soft)" }}
          />
        ))}
      </div>
    );
  }

  if (error && skills.length === 0) {
    return (
      <AppErrorState
        error={error}
        title="We couldn't load skills"
        description="The skills list is unavailable right now."
        onRetry={() => {
          void refetch();
        }}
        retryLabel="Retry"
      />
    );
  }

  const hasAnything =
    currentSkills.length > 0 ||
    pendingRemoveIds.length > 0 ||
    pendingAddSkills.length > 0;

  return (
    <div className="flex flex-col gap-5">
      {/* Skills currently in use by this Agent */}
      <div className="flex flex-col gap-2">
        {hasAnything && <SectionLabel>In use</SectionLabel>}

        {hasAnything ? (
          <div
            className="grid gap-4"
            style={{ gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))" }}
          >
            {currentSkills.map((skill) => (
              <AssignedSkillCard
                key={skill.id}
                skill={skill}
                href={skillDetailHref(scope, agent.organizationId, skill.id)}
                scope={scope}
                isRunning={isRunning}
                pin={pendingPins[skill.id] ?? skill.version}
                onPinChange={(version) =>
                  setPendingPins((prev) => {
                    const next = { ...prev };
                    if (version === skill.version) {
                      delete next[skill.id];
                    } else {
                      next[skill.id] = version;
                    }
                    return next;
                  })
                }
                onRemove={() => setSkillToRemove(skill)}
              />
            ))}

            {pendingRemoveIds.map((id) => {
              const skill = agent.skills.find((s) => s.id === id);
              if (!skill) return null;
              return (
                <SkillCard
                  key={`removing-${id}`}
                  skill={skill}
                  href={skillDetailHref(scope, agent.organizationId, skill.id)}
                  badges={
                    <>
                      <Badge variant="ok">In use</Badge>
                      <Badge variant="warn">Removing</Badge>
                    </>
                  }
                  footer={
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[0.75rem] line-through" style={{ color: "var(--ink-3)" }}>
                        {skill.name}
                      </span>
                      <button
                        type="button"
                        className="af-btn af-btn-sm af-btn-ghost"
                        onClick={() => undoRemoval(id)}
                      >
                        Undo
                      </button>
                    </div>
                  }
                />
              );
            })}

            {pendingAddSkills.map((skill) => (
              <SkillCard
                key={`adding-${skill.id}`}
                skill={skill}
                href={skillDetailHref(scope, agent.organizationId, skill.id)}
                badges={
                  <>
                    <Badge variant="ok">In use</Badge>
                    <Badge variant="accent">Adding</Badge>
                  </>
                }
                footer={
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[0.75rem]" style={{ color: "var(--ink-3)" }}>
                      · Adding
                    </span>
                    <button
                      type="button"
                      className="af-btn af-btn-sm af-btn-ghost"
                      onClick={() => cancelAdd(skill.id)}
                    >
                      Cancel
                    </button>
                  </div>
                }
              />
            ))}
          </div>
        ) : (
          <div
            className="py-6 text-center rounded-2xl text-[0.8125rem]"
            style={{ border: "1px dashed var(--line-strong)", color: "var(--ink-4)" }}
          >
            No skills in use yet.
          </div>
        )}
      </div>

      {/* Required credentials for newly added skills */}
      {newlyRequiredProviderIds.length > 0 && (
        <div className="flex flex-col gap-3">
          <SectionLabel>Required credentials</SectionLabel>
          {newlyRequiredProviderIds.map((providerId) => {
            const providerSpec = getIntegrationProvider(providerId);
            const draft = newSecretDrafts.find((d) => d.provider === providerId);
            if (!draft) return null;

            if (!providerSpec) {
              return (
                <div
                  key={providerId}
                  className="px-4 py-3 rounded-2xl text-[0.8125rem]"
                  style={{
                    border: "1px solid var(--line)",
                    background: "var(--bg-soft)",
                    color: "var(--ink-3)",
                  }}
                >
                  {credentialError && providerId === newlyRequiredProviderIds[0] && (
                    <CredentialErrorAlert
                      title="Could not save credentials"
                      message={credentialError}
                    />
                  )}
                  <span className="font-medium" style={{ color: "var(--ink)" }}>
                    {SKILL_PROVIDER_LABELS[providerId] ?? providerId}
                  </span>{" "}
                  — not yet configurable from the UI.
                </div>
              );
            }

            const isSharedEligible = !!SHARED_CREDENTIAL_PROVIDER_LABELS[providerId];
            const useShared = draft.sharedCredentialId !== undefined;
            const showCredentialError = Boolean(
              credentialError && providerId === newlyRequiredProviderIds[0],
            );

            return (
              <div
                key={providerId}
                className="flex flex-col gap-3.5 p-4 rounded-2xl"
                style={{ border: "1px solid var(--line)", background: "var(--bg-soft)" }}
              >
                <div className="font-semibold text-[0.844rem]" style={{ color: "var(--ink)" }}>
                  {providerSpec.label}
                </div>

                {isSharedEligible && (
                  <SharedManualToggle
                    provider={providerId}
                    useShared={useShared}
                    selectedId={draft.sharedCredentialId || undefined}
                    onSwitchToManual={() => switchToManual(providerId)}
                    onSwitchToShared={() => switchToShared(providerId)}
                    onPickShared={(brief) => handlePickShared(providerId, brief)}
                  />
                )}

                {showCredentialError && useShared && credentialError && (
                  <CredentialErrorAlert
                    title="Could not save credentials"
                    message={credentialError}
                  />
                )}

                {!useShared && (
                  <IntegrationFields
                    provider={providerSpec}
                    draft={draft}
                    namePrefix="tab-"
                    credentialError={showCredentialError ? credentialError : undefined}
                    onFieldChange={(key, value) => setField(providerId, key, value)}
                    onListChange={(key, values) => setRepos(providerId, key, values)}
                    onOAuthConnected={({ refreshToken, clientId, clientSecret, email, scopes }) => {
                      setFields(providerId, { refreshToken, clientId, clientSecret, email, scopes });
                    }}
                  />
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Skills */}
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between gap-2">
          <SectionLabel>Add skills</SectionLabel>
          <Link
            href={skillNewHref(scope, agent.organizationId)}
            className="af-btn af-btn-sm af-btn-ghost"
          >
            <Plus size={13} /> New private skill
          </Link>
        </div>
        <div
          className="flex items-center gap-2 px-3 py-2 rounded-xl"
          style={{ border: "1px solid var(--line)", background: "var(--bg-elev)" }}
        >
          <SearchIcon size={14} style={{ color: "var(--ink-4)", flexShrink: 0 }} />
          <input
            className="flex-1 text-[0.8125rem] outline-none bg-transparent"
            style={{ color: "var(--ink)" }}
            placeholder="Search skills…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        {isLoading && (
          <div className="text-[0.8125rem] py-4 text-center" style={{ color: "var(--ink-3)" }}>
            Loading…
          </div>
        )}
        {!isLoading &&
          currentSkills.length === 0 &&
          pendingRemoveIds.length === 0 &&
          pendingAddSkills.length === 0 &&
          availableSkills.length === 0 &&
          !hasNextPage && (
          <div className="text-[0.8125rem] py-4 text-center" style={{ color: "var(--ink-3)" }}>
            {search ? "No skills match." : "No skills available."}
          </div>
        )}
        {!isLoading && (
          <div
            className="grid gap-4"
            style={{ gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))" }}
          >
            {availableSkills.map((skill) => (
              <SkillCard
                key={skill.id}
                skill={skill}
                href={skillDetailHref(scope, agent.organizationId, skill.id)}
                addDisabled={isRunning}
                onAdd={() => addSkill(skill)}
              />
            ))}
            {hasNextPage && (
              <div
                ref={loadMoreRef}
                className="col-span-full flex items-center justify-center gap-2 py-4 text-[0.75rem]"
                style={{ color: "var(--ink-4)" }}
              >
                <Loader2 size={14} className={isFetchingNextPage ? "animate-spin" : "invisible"} />
                {isFetchingNextPage ? "Loading more skills…" : "Scroll to load more skills…"}
              </div>
            )}
            {isFetchingNextPageError && (
              <p className="col-span-full m-0 py-3 text-center text-[0.75rem]" style={{ color: "var(--err)" }}>
                Unable to load more skills. {" "}
                <button type="button" className="underline" onClick={() => void fetchNextPage()}>
                  Try again
                </button>
              </p>
            )}
          </div>
        )}
      </div>

      {credentialError && newlyRequiredProviderIds.length === 0 && (
        <CredentialErrorAlert
          title="Could not save changes"
          message={credentialError}
        />
      )}

      <ConfirmationDialog
        open={Boolean(skillToRemove)}
        onOpenChange={(open) => {
          if (!open) setSkillToRemove(null);
        }}
        title={`Remove ${skillToRemove?.name ?? "this skill"}?`}
        description={
          skillToRemove
            ? `This will stage ${skillToRemove.name} for removal from ${agent.name}. You can undo this before applying the skills changes.`
            : ""
        }
        confirmLabel="Remove skill"
        variant="destructive"
        onConfirm={confirmRemoval}
        icon={<Trash2 size={18} />}
      />
    </div>
  );
});

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="text-xs font-semibold uppercase tracking-[0.07em]"
      style={{ color: "var(--ink-4)" }}
    >
      {children}
    </div>
  );
}

function AssignedSkillCard({
  skill,
  href,
  scope,
  isRunning,
  pin,
  onPinChange,
  onRemove,
}: {
  skill: AgentAssignedSkill;
  href: string;
  scope: SkillScopeRef;
  isRunning: boolean;
  pin: number;
  onPinChange: (version: number) => void;
  onRemove: () => void;
}) {
  // Versions are fetched only once the picker is actually opened, not for every
  // assigned card on mount — an agent with a dozen skills would otherwise fire a
  // dozen requests just to render, for a control most cards never touch.
  const [pickerOpen, setPickerOpen] = useState(false);
  const { versions, isLoading: versionsLoading } = useSkillVersions(skill.id, scope, pickerOpen);
  return (
    <SkillCard
      skill={skill}
      href={href}
      badges={
        <>
          <Badge variant="ok">In use</Badge>
          {skill.required && <Badge>Required</Badge>}
        </>
      }
      footer={
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Select
            value={String(pin)}
            onValueChange={(value) => onPinChange(Number(value))}
            onOpenChange={setPickerOpen}
            disabled={isRunning || skill.required}
          >
            <SelectTrigger
              className="w-auto min-w-24"
              aria-label={`Version for ${skill.name}`}
              title={
                skill.required
                  ? "Pinned by the active template; publish a new template version to change it."
                  : undefined
              }
            >
              <SelectValue placeholder="Version" />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {/* Until the picker has been opened (and its fetch resolved), the
                  currently pinned version is the only option — Select needs a
                  matching Item mounted to show the trigger's label at rest, and
                  that's the one version we already know without a request. */}
                {(pickerOpen && versions.length > 0 ? versions.map((v) => v.version) : [pin]).map((version) => (
                  <SelectItem key={version} value={String(version)}>
                    Version v{version}
                  </SelectItem>
                ))}
                {pickerOpen && versionsLoading && versions.length === 0 && (
                  <div className="px-2 py-1.5 text-[0.78rem]" style={{ color: "var(--ink-4)" }}>
                    Loading versions…
                  </div>
                )}
              </SelectGroup>
            </SelectContent>
          </Select>
          {skill.required ? (
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <span>
                    <button type="button" className="af-btn af-btn-sm af-btn-ghost" disabled>
                      Remove
                    </button>
                  </span>
                </TooltipTrigger>
                <TooltipContent>Required by template</TooltipContent>
              </Tooltip>
            </TooltipProvider>
          ) : (
            <button
              type="button"
              className="af-btn af-btn-sm af-btn-ghost"
              disabled={isRunning}
              onClick={onRemove}
            >
              Remove
            </button>
          )}
        </div>
      }
    />
  );
}
