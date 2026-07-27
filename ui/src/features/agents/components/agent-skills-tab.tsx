"use client";

import { useState } from "react";
import { useDebouncedValue } from "@tanstack/react-pacer";

import { AppErrorState } from "@/components/app-error-state";
import { SearchIcon } from "@/components/icons";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { useSkills } from "@/features/skills/hooks/use-skills";
import { SKILL_PROVIDER_LABELS } from "@/features/skills/utils";
import { SkillSourceBadge } from "@/features/skills/components/skill-drawer";
import type { Skill } from "@/features/skills/schemas";

import {
  coerceBooleanFields,
  expandGithubContent,
  getIntegrationProvider,
  hasIncompleteIntegration,
  isOAuthConnected,
  type IntegrationDraft,
} from "../integrations";
import { SharedCredentialPicker } from "@/features/shared-credentials/components/shared-credential-picker";
import { SHARED_CREDENTIAL_PROVIDER_LABELS } from "@/features/shared-credentials/utils";
import type { SharedCredentialBrief } from "@/features/shared-credentials/schemas";
import { FormField, GoogleAuthButton, TokenInput } from "./hire-dialog-primitives";
import { RepoListField } from "./hire-dialog-steps";
import { useUpdateAgent } from "../hooks/use-update-agent";
import type { Agent, AgentAssignedSkill } from "../schemas";

interface AgentSkillsTabProps {
  agent: Agent;
  isRunning: boolean;
}

export function AgentSkillsTab({ agent, isRunning }: AgentSkillsTabProps) {
  const [search, setSearch] = useState("");
  const [debouncedSearch] = useDebouncedValue(search, { wait: 300 });
  const { skills, isLoading, error, refetch } = useSkills({ search: debouncedSearch || undefined, pageSize: 100 });
  const updateAgent = useUpdateAgent();

  const [pendingAddIds, setPendingAddIds] = useState<string[]>([]);
  const [pendingRemoveIds, setPendingRemoveIds] = useState<string[]>([]);
  const [newSecretDrafts, setNewSecretDrafts] = useState<IntegrationDraft[]>([]);
  const [visible, setVisible] = useState<Record<string, boolean>>({});
  const [saved, setSaved] = useState(false);

  const existingSecretProviders = new Set(
    (agent.secrets ?? []).map((s) => s.provider),
  );

  const currentSkills = agent.skills.filter(
    (s) => !pendingRemoveIds.includes(s.id),
  );

  const pendingAddSkills = skills.filter((s) => pendingAddIds.includes(s.id));

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

  const hasPendingChanges =
    pendingAddIds.length > 0 || pendingRemoveIds.length > 0;

  function addSkill(skill: Skill) {
    const needed = skill.requiredProviders.filter(
      (p) => !existingSecretProviders.has(p),
    );
    setPendingAddIds((prev) => [...prev, skill.id]);
    setNewSecretDrafts((prev) => {
      const existing = new Set(prev.map((d) => d.provider));
      const toAdd = needed.filter((p) => !existing.has(p));
      return [...prev, ...toAdd.map((p) => ({ provider: p, content: {} }))];
    });
  }

  function cancelAdd(skillId: string) {
    const remaining = skills.filter(
      (s) => pendingAddIds.includes(s.id) && s.id !== skillId,
    );
    const stillNeeded = new Set(
      remaining
        .flatMap((s) => s.requiredProviders)
        .filter((p) => !existingSecretProviders.has(p)),
    );
    setPendingAddIds((prev) => prev.filter((id) => id !== skillId));
    setNewSecretDrafts((prev) =>
      prev.filter((d) => stillNeeded.has(d.provider)),
    );
  }

  function markForRemoval(skillId: string) {
    setPendingRemoveIds((prev) => [...prev, skillId]);
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

  function switchToShared(provider: string) {
    setNewSecretDrafts((prev) =>
      prev.map((d) =>
        d.provider === provider
          ? { ...d, content: {}, sharedCredentialId: "" }
          : d,
      ),
    );
  }

  function switchToManual(provider: string) {
    setNewSecretDrafts((prev) =>
      prev.map((d) =>
        d.provider === provider
          ? { ...d, sharedCredentialId: undefined }
          : d,
      ),
    );
  }

  function handlePickShared(provider: string, brief: SharedCredentialBrief | null) {
    setNewSecretDrafts((prev) =>
      prev.map((d) =>
        d.provider === provider
          ? { ...d, sharedCredentialId: brief?.id ?? "" }
          : d,
      ),
    );
  }

  async function handleSave() {
    updateAgent.reset();
    try {
      // Providers required by skills that survive this update (kept + newly added).
      const survivingSkills = [
        ...agent.skills.filter((s) => !pendingRemoveIds.includes(s.id)),
        ...skills.filter((s) => pendingAddIds.includes(s.id)),
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
      setPendingRemoveIds([]);
      setNewSecretDrafts([]);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch {
      // error displayed via updateAgent.error
    }
  }

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

  if (error) {
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
      {/* Assigned skills */}
      <div className="flex flex-col gap-2">
        {hasAnything && (
          <SectionLabel>Assigned</SectionLabel>
        )}

        {currentSkills.map((skill) => (
          <AssignedSkillRow
            key={skill.id}
            skill={skill}
            isRunning={isRunning}
            onRemove={() => markForRemoval(skill.id)}
          />
        ))}

        {pendingRemoveIds.map((id) => {
          const skill = agent.skills.find((s) => s.id === id);
          if (!skill) return null;
          return (
            <div
              key={id}
              className="flex items-center gap-2 px-3.5 py-2.5 rounded-2xl"
              style={{ border: "1px dashed var(--line)", opacity: 0.55 }}
            >
              <span
                className="flex-1 font-medium text-[0.844rem] line-through"
                style={{ color: "var(--ink-3)" }}
              >
                {skill.name}
              </span>
              <button
                className="af-btn af-btn-sm af-btn-ghost"
                onClick={() => undoRemoval(id)}
              >
                Undo
              </button>
            </div>
          );
        })}

        {pendingAddSkills.map((skill) => (
          <div
            key={skill.id}
            className="flex items-center gap-2 px-3.5 py-2.5 rounded-2xl"
            style={{ border: "1.5px dashed var(--line)", background: "var(--bg-soft)" }}
          >
            <div className="flex-1 min-w-0">
              <span className="font-medium text-[0.844rem]" style={{ color: "var(--ink)" }}>
                {skill.name}
              </span>
              <span className="ml-2 text-[0.75rem]" style={{ color: "var(--ink-4)" }}>
                · Adding
              </span>
            </div>
            <button
              className="af-btn af-btn-sm af-btn-ghost"
              onClick={() => cancelAdd(skill.id)}
            >
              Cancel
            </button>
          </div>
        ))}

        {!hasAnything && (
          <div
            className="py-6 text-center rounded-2xl text-[0.8125rem]"
            style={{ border: "1px dashed var(--line-strong)", color: "var(--ink-4)" }}
          >
            No skills assigned yet.
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
                  <span className="font-medium" style={{ color: "var(--ink)" }}>
                    {SKILL_PROVIDER_LABELS[providerId] ?? providerId}
                  </span>{" "}
                  — not yet configurable from the UI.
                </div>
              );
            }

            const isSharedEligible = !!SHARED_CREDENTIAL_PROVIDER_LABELS[providerId];
            const useShared = draft.sharedCredentialId !== undefined;

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
                  <div className="flex gap-1.5">
                    <button
                      type="button"
                      className="af-btn af-btn-sm"
                      style={
                        !useShared
                          ? { background: "var(--ink)", color: "var(--bg)", borderColor: "var(--ink)" }
                          : undefined
                      }
                      onClick={() => switchToManual(providerId)}
                    >
                      Enter credentials
                    </button>
                    <button
                      type="button"
                      className="af-btn af-btn-sm"
                      style={
                        useShared
                          ? { background: "var(--ink)", color: "var(--bg)", borderColor: "var(--ink)" }
                          : undefined
                      }
                      onClick={() => switchToShared(providerId)}
                    >
                      Use shared credential
                    </button>
                  </div>
                )}

                {useShared ? (
                  <SharedCredentialPicker
                    provider={providerId}
                    value={draft.sharedCredentialId || undefined}
                    onChange={(brief) => handlePickShared(providerId, brief)}
                  />
                ) : (
                  <>
                    {providerSpec.authMethod === "google_oauth" && (
                      <GoogleAuthButton
                        connected={isOAuthConnected(draft)}
                        onConnected={({ refreshToken, clientId, clientSecret }) => {
                          setField(providerId, "refreshToken", refreshToken);
                          setField(providerId, "clientId", clientId);
                          setField(providerId, "clientSecret", clientSecret);
                        }}
                      />
                    )}
                    {providerSpec.fields.map((field) => {
                      if (field.dependsOn && draft.content[field.dependsOn.key] !== field.dependsOn.value) {
                        return null;
                      }
                      const label = field.required
                        ? field.label
                        : `${field.label} (optional)`;

                      if (field.type === "repo-list") {
                        const repos = Array.isArray(draft.content[field.key])
                          ? (draft.content[field.key] as string[])
                          : [];
                        return (
                          <FormField key={field.key} label={label} hint={field.hint}>
                            <RepoListField
                              repos={repos}
                              onChange={(next) => setRepos(providerId, field.key, next)}
                              placeholder={field.placeholder}
                            />
                          </FormField>
                        );
                      }

                      const rawValue = draft.content[field.key];
                      const value = typeof rawValue === "string" ? rawValue : "";

                      if (field.type === "secret") {
                        const vkey = `${providerId}:${field.key}`;
                        return (
                          <FormField key={field.key} label={label} hint={field.hint}>
                            <TokenInput
                              value={value}
                              onChange={(v) => setField(providerId, field.key, v)}
                              visible={!!visible[vkey]}
                              onToggle={() =>
                                setVisible((s) => ({ ...s, [vkey]: !s[vkey] }))
                              }
                              placeholder={field.placeholder}
                            />
                          </FormField>
                        );
                      }

                      if (field.type === "radio") {
                        return (
                          <FormField key={field.key} label={label} hint={field.hint}>
                            <div className="flex flex-col gap-2 mt-1">
                              {field.options?.map((opt) => (
                                <label key={opt.value} className="flex items-center gap-2 cursor-pointer">
                                  <input
                                    type="radio"
                                    name={`tab-${providerId}-${field.key}`}
                                    value={opt.value}
                                    checked={value === opt.value}
                                    onChange={(e) => setField(providerId, field.key, e.target.value)}
                                    className="accent-[var(--blue-9)]"
                                  />
                                  <span className="text-[13px]" style={{ color: "var(--ink-1)" }}>{opt.label}</span>
                                </label>
                              ))}
                            </div>
                          </FormField>
                        );
                      }

                      return (
                        <FormField key={field.key} label={label} hint={field.hint}>
                          <input
                            className="af-input"
                            value={value}
                            onChange={(e) =>
                              setField(providerId, field.key, e.target.value)
                            }
                            placeholder={field.placeholder}
                            autoComplete="off"
                          />
                        </FormField>
                      );
                    })}
                  </>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Available skills to add */}
      <div className="flex flex-col gap-2">
        <SectionLabel>Add skills</SectionLabel>
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
        {!isLoading && availableSkills.length === 0 && (
          <div className="text-[0.8125rem] py-4 text-center" style={{ color: "var(--ink-3)" }}>
            {search ? "No skills match." : "No more skills to add."}
          </div>
        )}
        {!isLoading && availableSkills.map((skill) => (
          <AvailableSkillRow
            key={skill.id}
            skill={skill}
            isRunning={isRunning}
            onAdd={() => addSkill(skill)}
          />
        ))}
      </div>

      {/* Save */}
      {hasPendingChanges && (
        <div className="flex gap-2 items-center">
          <button
            className="af-btn af-btn-sm"
            disabled={
              isRunning ||
              updateAgent.isPending ||
              hasIncompleteIntegration(newSecretDrafts)
            }
            onClick={() => {
              void handleSave();
            }}
          >
            {updateAgent.isPending ? "Saving…" : saved ? "Saved!" : "Save changes"}
          </button>
          {updateAgent.error && (
            <span className="text-xs" style={{ color: "var(--err)" }}>
              {updateAgent.error instanceof Error
                ? updateAgent.error.message
                : "Save failed"}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

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

function AssignedSkillRow({
  skill,
  isRunning,
  onRemove,
}: {
  skill: AgentAssignedSkill;
  isRunning: boolean;
  onRemove: () => void;
}) {
  return (
    <div
      className="flex items-center gap-2 px-3.5 py-2.5 rounded-2xl"
      style={{ border: "1px solid var(--line)", background: "var(--bg-soft)" }}
    >
      <div className="flex items-center gap-2 flex-1 min-w-0">
        <span className="font-medium text-[0.844rem]" style={{ color: "var(--ink)" }}>
          {skill.name}
        </span>
        <SkillSourceBadge source={skill.source} />
        {skill.required && (
          <span
            className="text-[0.6875rem] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full"
            style={{ color: "var(--ink-3)", background: "var(--line)" }}
          >
            Required
          </span>
        )}
      </div>
      {skill.required ? (
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <span>
                <button className="af-btn af-btn-sm af-btn-ghost" disabled>
                  Remove
                </button>
              </span>
            </TooltipTrigger>
            <TooltipContent>Required by template</TooltipContent>
          </Tooltip>
        </TooltipProvider>
      ) : (
        <button
          className="af-btn af-btn-sm af-btn-ghost"
          disabled={isRunning}
          onClick={onRemove}
        >
          Remove
        </button>
      )}
    </div>
  );
}

function AvailableSkillRow({
  skill,
  isRunning,
  onAdd,
}: {
  skill: Skill;
  isRunning: boolean;
  onAdd: () => void;
}) {
  return (
    <div
      className="flex items-center gap-2 px-3.5 py-2.5 rounded-2xl"
      style={{ border: "1px solid var(--line)" }}
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-medium text-[0.844rem]" style={{ color: "var(--ink)" }}>
            {skill.name}
          </span>
          <SkillSourceBadge source={skill.source} />
        </div>
        {skill.requiredProviders.length > 0 && (
          <span className="text-[0.75rem]" style={{ color: "var(--ink-4)" }}>
            Requires:{" "}
            {skill.requiredProviders
              .map((p) => SKILL_PROVIDER_LABELS[p] ?? p)
              .join(", ")}
          </span>
        )}
      </div>
      <button
        className="af-btn af-btn-sm af-btn-ghost"
        disabled={isRunning}
        onClick={onAdd}
      >
        Add
      </button>
    </div>
  );
}