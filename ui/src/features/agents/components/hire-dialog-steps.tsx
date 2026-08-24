"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDownIcon } from "lucide-react";
import { PlusIcon, SearchIcon, XIcon } from "@/components/icons";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { SharedManualToggle } from "@/features/shared-credentials/components/shared-manual-toggle";
import { useSharedManualSwitch } from "@/features/shared-credentials/hooks/use-shared-manual-switch";
import { SHARED_CREDENTIAL_PROVIDER_LABELS } from "@/features/shared-credentials/utils";
import { useSkills } from "@/features/skills/hooks/use-skills";
import { SKILL_PROVIDER_LABELS } from "@/features/skills/utils";
import type { Skill } from "@/features/skills/schemas";
import { SkillSourceBadge } from "@/features/skills/components/skill-source-badge";

import {
  INTEGRATION_PROVIDERS,
  getIntegrationProvider,
  isAutoConfiguredProvider,
  type IntegrationDraft,
} from "../integrations";
import type { AgentAssignedSkill, AgentTemplateRead, TemplateRequiredSkill } from "../schemas";
import { useTemplates } from "../hooks/use-templates";
import type { RequiredSkillGroup } from "../utils";
import { IntegrationFields } from "./integration-fields";
import { Pagination } from "./pagination";

const HIRE_DIALOG_PAGE_SIZE = 6;

export const TEMPLATE_FILE_KEYS = [
  "soulMd",
  "identityMd",
  "toolsMd",
  "agentsMd",
  "bootMd",
  "bootstrapMd",
  "heartbeatMd",
] as const;

export type TemplateFileKey = (typeof TEMPLATE_FILE_KEYS)[number];

export function templateFileLabel(key: TemplateFileKey): string {
  return key.replace("Md", "").toUpperCase() + ".md";
}

export function TemplateSourceBadge({
  source,
  isFork = false,
}: {
  source: AgentTemplateRead["templateSource"];
  isFork?: boolean;
}) {
  if (source !== "pre-defined") return null;
  return (
    <span
      className="text-[0.6875rem] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full"
      style={
        isFork
          ? { color: "var(--accent-ink)", background: "var(--accent-soft)" }
          : { color: "var(--ink-3)", background: "var(--line)" }
      }
      title={isFork ? "Organization fork of a Platform Template" : "Platform Template"}
    >
      {isFork ? "Org fork" : "Built-in"}
    </span>
  );
}

// Shared lineage version picker — used at hire time, in the template drawer,
// and in the agent re-pin panel. Marks the highest version as "latest".
export function VersionSelect({
  versions,
  selectedVersion,
  onChange,
  disabled,
  ariaLabel = "Version",
}: {
  versions: AgentTemplateRead[];
  selectedVersion: number | null;
  onChange: (version: number) => void;
  disabled?: boolean;
  ariaLabel?: string;
}) {
  const latest = versions[0]?.version;
  const resolved = selectedVersion ?? latest ?? null;
  const displayLabel =
    resolved != null
      ? `v${resolved}${resolved === latest ? " (latest)" : ""}`
      : "Select…";

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          className="af-btn af-btn-sm flex items-center gap-1.5"
          aria-label={ariaLabel}
          disabled={disabled || versions.length === 0}
        >
          <span>{displayLabel}</span>
          <ChevronDownIcon size={12} className="opacity-50 flex-shrink-0" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent>
        <DropdownMenuRadioGroup
          value={resolved != null ? String(resolved) : ""}
          onValueChange={(v) => onChange(Number(v))}
        >
          {versions.map((v) => (
            <DropdownMenuRadioItem key={v.version} value={String(v.version)}>
              v{v.version}
              {v.version === latest ? " (latest)" : ""}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function ClampedDescription({ text }: { text: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [clamped, setClamped] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (el) setClamped(el.scrollHeight > el.clientHeight);
  }, [text]);

  const inner = (
    <div
      ref={ref}
      className="text-[0.75rem] leading-[1.4] overflow-hidden cursor-default"
      style={{
        color: "var(--ink-3)",
        display: "-webkit-box",
        WebkitLineClamp: 3,
        WebkitBoxOrient: "vertical",
      }}
    >
      {text}
    </div>
  );

  if (!clamped) return inner;

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>{inner}</TooltipTrigger>
        <TooltipContent side="top">{text}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

export function TemplateStep({
  selectedKey,
  onPick,
  versions,
  versionsLoading,
  selectedVersion,
  onVersionChange,
}: {
  selectedKey: string | null;
  onPick: (template: AgentTemplateRead) => void;
  versions: AgentTemplateRead[];
  versionsLoading: boolean;
  selectedVersion: number | null;
  onVersionChange: (version: number) => void;
}) {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);

  const { templates, total, isLoading, error } = useTemplates({
    search: search || undefined,
    page,
    pageSize: HIRE_DIALOG_PAGE_SIZE,
  });

  const totalPages = Math.max(1, Math.ceil(total / HIRE_DIALOG_PAGE_SIZE));


  function handleSearchChange(value: string) {
    setSearch(value);
    setPage(1);
  }

  return (
    <div className="flex flex-col gap-3">
      <div
        className="flex items-center gap-2 px-3 py-2 rounded-xl"
        style={{ border: "1px solid var(--line)", background: "var(--bg-elev)" }}
      >
        <SearchIcon size={14} style={{ color: "var(--ink-4)", flexShrink: 0 }} />
        <input
          className="flex-1 text-[0.8125rem] outline-none bg-transparent"
          style={{ color: "var(--ink)" }}
          placeholder="Search templates…"
          value={search}
          onChange={(e) => handleSearchChange(e.target.value)}
        />
      </div>

      <div style={{ minHeight: "22rem" }}>
      {isLoading && (
        <div className="text-[0.8125rem] py-8 text-center" style={{ color: "var(--ink-3)" }}>
          Loading templates…
        </div>
      )}
      {!isLoading && error && (
        <div className="text-[0.8125rem] py-8 text-center" style={{ color: "var(--err)" }}>
          Could not load templates. Please try again.
        </div>
      )}
      {!isLoading && !error && templates.length === 0 && (
        <div className="text-[0.8125rem] py-8 text-center" style={{ color: "var(--ink-3)" }}>
          {search ? "No templates match." : "No templates yet. Create one in Settings → Templates first."}
        </div>
      )}

      {!isLoading && !error && templates.length > 0 && (
        <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
          {templates.map((t) => (
            <div
              key={t.templateKey}
              className="flex flex-col gap-1.5 p-4 rounded-2xl cursor-default transition-colors min-h-[4.5rem]"
              style={{
                border: selectedKey === t.templateKey ? "1.5px solid var(--ink)" : "1.5px solid var(--line)",
                background: selectedKey === t.templateKey ? "var(--bg-soft)" : "var(--bg-elev)",
              }}
              onClick={() => onPick(t)}
            >
              <div className="flex items-center justify-between gap-2">
                <div className="font-semibold text-[0.844rem]" style={{ color: "var(--ink)" }}>{t.templateName}</div>
                <TemplateSourceBadge
                  source={t.templateSource}
                  isFork={Boolean(t.forkedFromPlatformTemplateId)}
                />
              </div>
              {t.description && <ClampedDescription text={t.description} />}
              <div className="mt-1">
                {selectedKey === t.templateKey ? (
                  <div onClick={(e) => e.stopPropagation()}>
                    {versionsLoading ? (
                      <span className="text-[0.75rem]" style={{ color: "var(--ink-3)" }}>Loading…</span>
                    ) : (
                      <VersionSelect
                        versions={versions}
                        selectedVersion={selectedVersion}
                        onChange={onVersionChange}
                      />
                    )}
                  </div>
                ) : (
                  <div className="h-8" />
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      </div>

      <div style={{ minHeight: "1.875rem" }}>
        <Pagination page={page} totalPages={totalPages} onPageChange={setPage} />
      </div>
    </div>
  );
}

// Free-text repeatable list of repo names — Enter/Add appends a chip, X removes one.
export function SkillsStep({
  selectedSkillIds,
  skillCredentials,
  onSkillIdsChange,
  onSkillCredentialsChange,
  templateRequiredSkills = [],
  requiredGroups = [],
  groupChoices = {},
  onGroupChoiceChange,
}: {
  selectedSkillIds: string[];
  skillCredentials: IntegrationDraft[];
  onSkillIdsChange: (ids: string[]) => void;
  onSkillCredentialsChange: (drafts: IntegrationDraft[]) => void;
  templateRequiredSkills?: AgentAssignedSkill[];
  requiredGroups?: RequiredSkillGroup[];
  groupChoices?: Record<string, string[]>;
  onGroupChoiceChange?: (groupKey: string, skillId: string) => void;
}) {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);

  const { switchToShared, switchToManual, handlePickShared } = useSharedManualSwitch(
    skillCredentials,
    onSkillCredentialsChange,
  );

  const { skills, total, isLoading } = useSkills({
    search: search || undefined,
    page,
    pageSize: HIRE_DIALOG_PAGE_SIZE,
  });

  const totalPages = Math.max(1, Math.ceil(total / HIRE_DIALOG_PAGE_SIZE));

  const requiredSkillIds = new Set(templateRequiredSkills.map((s) => s.id));
  const groupMemberIds = new Set(requiredGroups.flatMap((g) => g.members.map((m) => m.id)));
  const orderedSkills = [
    ...skills.filter((s) => requiredSkillIds.has(s.id)),
    ...skills.filter((s) => !requiredSkillIds.has(s.id) && !groupMemberIds.has(s.id)),
  ];

  const chosenGroupSkills: TemplateRequiredSkill[] = requiredGroups.flatMap((g) =>
    (groupChoices[g.key] ?? [])
      .map((id) => g.members.find((m) => m.id === id))
      .filter((s): s is TemplateRequiredSkill => !!s),
  );

  // Track full Skill objects for selected skills so we can compute requiredProviders
  // across pages. Users can only toggle visible skills, so this stays in sync.
  const [selectedSkillObjects, setSelectedSkillObjects] = useState<Skill[]>([]);
  const requiredProviderIds: string[] = [
    ...new Set([
      ...templateRequiredSkills.flatMap((s) => s.requiredProviders),
      ...chosenGroupSkills.flatMap((s) => s.requiredProviders),
      ...selectedSkillObjects.flatMap((s) => s.requiredProviders),
    ]),
  ];

  function handleSearchChange(value: string) {
    setSearch(value);
    setPage(1);
  }

  // Rebuilds skillCredentials to hold exactly one draft per currently-required
  // provider, preserving existing drafts for providers still required and
  // dropping ones that no longer are (e.g. switching a group's choice from
  // GitHub to Bitbucket drops the stale GitHub draft).
  function syncCredentialDrafts(requiredProviders: Set<string>) {
    const newCreds = skillCredentials.filter((c) => requiredProviders.has(c.provider));
    for (const p of requiredProviders) {
      // Auto-configured providers are derived from the agent's configuration and
      // must never appear in the secrets payload.
      if (!isAutoConfiguredProvider(p) && !newCreds.find((c) => c.provider === p)) {
        newCreds.push({ provider: p, content: {} });
      }
    }
    onSkillCredentialsChange(newCreds);
  }

  function toggleSkill(skill: Skill) {
    const isSelected = selectedSkillIds.includes(skill.id);
    const newIds = isSelected
      ? selectedSkillIds.filter((id) => id !== skill.id)
      : [...selectedSkillIds, skill.id];
    const newObjects = isSelected
      ? selectedSkillObjects.filter((s) => s.id !== skill.id)
      : [...selectedSkillObjects, skill];

    const newRequired = new Set([
      ...templateRequiredSkills.flatMap((s) => s.requiredProviders),
      ...chosenGroupSkills.flatMap((s) => s.requiredProviders),
      ...newObjects.flatMap((s) => s.requiredProviders),
    ]);
    syncCredentialDrafts(newRequired);

    onSkillIdsChange(newIds);
    setSelectedSkillObjects(newObjects);
  }

  function toggleGroupMember(groupKey: string, member: TemplateRequiredSkill) {
    const current = groupChoices[groupKey] ?? [];
    const nextIdsForGroup = current.includes(member.id)
      ? current.filter((id) => id !== member.id)
      : [...current, member.id];
    const newChosen = requiredGroups.flatMap((g) =>
      (g.key === groupKey ? nextIdsForGroup : groupChoices[g.key] ?? [])
        .map((id) => g.members.find((m) => m.id === id))
        .filter((s): s is TemplateRequiredSkill => !!s),
    );
    const newRequired = new Set([
      ...templateRequiredSkills.flatMap((s) => s.requiredProviders),
      ...newChosen.flatMap((s) => s.requiredProviders),
      ...selectedSkillObjects.flatMap((s) => s.requiredProviders),
    ]);
    syncCredentialDrafts(newRequired);
    onGroupChoiceChange?.(groupKey, member.id);
  }

  function setField(providerId: string, key: string, value: string) {
    setFields(providerId, { [key]: value });
  }
  /** Apply several keys in ONE update.
   *
   * These helpers derive the next list from the closed-over prop rather than from a
   * functional setState, so successive calls in the same tick all read the same stale
   * value and the last one wins. The OAuth flow writes refreshToken, clientId and
   * clientSecret together, which silently discarded the token. */
  function setFields(providerId: string, patch: Record<string, string>) {
    onSkillCredentialsChange(
      skillCredentials.map((c) =>
        c.provider === providerId
          ? { ...c, content: { ...c.content, ...patch } }
          : c,
      ),
    );
  }

  function setRepos(providerId: string, key: string, repos: string[]) {
    onSkillCredentialsChange(
      skillCredentials.map((c) =>
        c.provider === providerId
          ? { ...c, content: { ...c.content, [key]: repos } }
          : c,
      ),
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <p className="text-[0.8125rem] leading-[1.5]" style={{ color: "var(--ink-3)" }}>
        Choose skills to assign to this agent. Required credentials will appear below as you select skills.
      </p>

      {requiredGroups.map((group) => (
        <div key={group.key} className="flex flex-col gap-2">
          <div className="text-[0.8125rem] font-medium" style={{ color: "var(--ink)" }}>
            Required by template — choose at least one
          </div>
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
            {group.members.map((member) => {
              const chosen = (groupChoices[group.key] ?? []).includes(member.id);
              return (
                <div
                  key={member.id}
                  role="checkbox"
                  aria-checked={chosen}
                  className="flex flex-col gap-1.5 p-4 rounded-2xl transition-colors min-h-[4.5rem]"
                  style={{
                    cursor: "pointer",
                    border: chosen ? "1.5px solid var(--ink)" : "1.5px solid var(--line)",
                    background: chosen ? "var(--bg-soft)" : "var(--bg-elev)",
                  }}
                  onClick={() => toggleGroupMember(group.key, member)}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="font-semibold text-[0.844rem]" style={{ color: "var(--ink)" }}>
                      {member.name}
                    </div>
                    <SkillSourceBadge source={member.source} />
                  </div>
                  <div className="text-[0.6875rem]" style={{ color: "var(--ink-3)" }}>
                    {chosen ? "Selected" : "Required by template"}
                  </div>
                  {member.requiredProviders.length > 0 && (
                    <div className="text-[0.75rem]" style={{ color: "var(--ink-4)" }}>
                      {member.requiredProviders.map((p) => SKILL_PROVIDER_LABELS[p] ?? p).join(", ")}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      ))}

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
          onChange={(e) => handleSearchChange(e.target.value)}
        />
      </div>

      <div style={isLoading ? { minHeight: "22rem" } : undefined}>
        {isLoading && (
          <div className="text-[0.8125rem] py-8 text-center" style={{ color: "var(--ink-3)" }}>
            Loading skills…
          </div>
        )}
        {!isLoading && total === 0 && !search && (
          <div
            className="text-[0.8125rem] py-6 text-center rounded-2xl"
            style={{ border: "1px dashed var(--line-strong)", color: "var(--ink-4)" }}
          >
            No skills available. Create skills in <strong>Settings → Skills</strong> first.
          </div>
        )}
        {!isLoading && total === 0 && search && (
          <div className="text-[0.8125rem] py-8 text-center" style={{ color: "var(--ink-3)" }}>
            No skills match.
          </div>
        )}
        {!isLoading && skills.length > 0 && (
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
            {orderedSkills.map((skill) => {
              const isRequired = requiredSkillIds.has(skill.id);
              const selected = isRequired || selectedSkillIds.includes(skill.id);
              const disabled = false;
              return (
                <div
                  key={skill.id}
                  className="flex flex-col gap-1.5 p-4 rounded-2xl transition-colors min-h-[4.5rem]"
                  style={{
                    cursor: isRequired || disabled ? "default" : "pointer",
                    border: selected ? "1.5px solid var(--ink)" : "1.5px solid var(--line)",
                    background: selected ? "var(--bg-soft)" : "var(--bg-elev)",
                    opacity: disabled ? 0.5 : 1,
                  }}
                  onClick={() => { if (!isRequired && !disabled) toggleSkill(skill); }}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="font-semibold text-[0.844rem]" style={{ color: "var(--ink)" }}>
                      {skill.name}
                    </div>
                    <SkillSourceBadge source={skill.source} />
                  </div>
                  {isRequired && (
                    <div className="text-[0.6875rem]" style={{ color: "var(--ink-3)" }}>
                      Required by template
                    </div>
                  )}
                  {skill.requiredProviders.length > 0 && (
                    <div className="text-[0.75rem]" style={{ color: "var(--ink-4)" }}>
                      {skill.requiredProviders.map((p) => SKILL_PROVIDER_LABELS[p] ?? p).join(", ")}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      <Pagination page={page} totalPages={totalPages} onPageChange={setPage} />

      {requiredProviderIds.length > 0 && (
        <div className="flex flex-col gap-3.5">
          <div className="font-medium text-[0.844rem]" style={{ color: "var(--ink)" }}>
            Required credentials
          </div>
          {requiredProviderIds.map((providerId) => {
            const providerSpec = getIntegrationProvider(providerId);
            const draft = skillCredentials.find((c) => c.provider === providerId);
            if (!draft) return null;

            if (!providerSpec) {
              return (
                <div
                  key={providerId}
                  className="px-4 py-3 rounded-2xl text-[0.8125rem]"
                  style={{ border: "1px solid var(--line)", background: "var(--bg-soft)", color: "var(--ink-3)" }}
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
                  <span
                    className="ml-2 text-[0.6875rem] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full"
                    style={{ color: "var(--ink-3)", background: "var(--line)" }}
                  >
                    Required
                  </span>
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

                {!useShared && (
                  <IntegrationFields
                    provider={providerSpec}
                    draft={draft}
                    showScopeNote
                    onFieldChange={(key, value) => setField(providerId, key, value)}
                    onReposChange={(key, repos) => setRepos(providerId, key, repos)}
                    onOAuthConnected={({ refreshToken, clientId, clientSecret }) => {
                      setFields(providerId, { refreshToken, clientId, clientSecret });
                    }}
                  />
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function IntegrationsStep({
  integrations,
  onChange,
}: {
  integrations: IntegrationDraft[];
  onChange: (next: IntegrationDraft[]) => void;
}) {

  const { switchToShared, switchToManual, handlePickShared } = useSharedManualSwitch(
    integrations,
    onChange,
  );

  const usedProviders = new Set(integrations.map((i) => i.provider));
  const available = INTEGRATION_PROVIDERS.filter((p) => !usedProviders.has(p.id));

  function addProvider(id: string) {
    onChange([...integrations, { provider: id, content: {} }]);
  }
  function removeProvider(id: string) {
    onChange(integrations.filter((i) => i.provider !== id));
  }
  function setField(providerId: string, key: string, value: string) {
    setFields(providerId, { [key]: value });
  }
  /** Apply several keys in ONE update — see the note on the sibling step: successive
   * single-key calls in the same tick overwrite each other, which dropped the OAuth
   * refresh token. */
  function setFields(providerId: string, patch: Record<string, string>) {
    onChange(
      integrations.map((i) =>
        i.provider === providerId
          ? { ...i, content: { ...i.content, ...patch } }
          : i,
      ),
    );
  }
  function setRepos(providerId: string, key: string, repos: string[]) {
    onChange(
      integrations.map((i) =>
        i.provider === providerId
          ? { ...i, content: { ...i.content, [key]: repos } }
          : i,
      ),
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <p className="text-[0.8125rem] leading-[1.5]" style={{ color: "var(--ink-3)" }}>
        Connect external tools your agent can use. Credentials are encrypted in the key vault.
        {" This step is optional — you can hire without any."}
      </p>

      {integrations.map((draft) => {
        const provider = getIntegrationProvider(draft.provider);
        if (!provider) return null;
        const isSharedEligible = !!SHARED_CREDENTIAL_PROVIDER_LABELS[draft.provider];
        const useShared = draft.sharedCredentialId !== undefined;

        return (
          <div
            key={draft.provider}
            className="flex flex-col gap-3.5 p-4 rounded-2xl"
            style={{ border: "1px solid var(--line)", background: "var(--bg-soft)" }}
          >
            <div className="flex items-center justify-between">
              <div className="font-semibold text-[0.844rem]" style={{ color: "var(--ink)" }}>
                {provider.label}
              </div>
              <button
                type="button"
                className="af-btn af-btn-ghost af-btn-icon"
                onClick={() => removeProvider(draft.provider)}
                aria-label={`Remove ${provider.label}`}
              >
                <XIcon size={15} />
              </button>
            </div>

            {isSharedEligible && (
              <SharedManualToggle
                provider={draft.provider}
                useShared={useShared}
                selectedId={draft.sharedCredentialId || undefined}
                onSwitchToManual={() => switchToManual(draft.provider)}
                onSwitchToShared={() => switchToShared(draft.provider)}
                onPickShared={(brief) => handlePickShared(draft.provider, brief)}
              />
            )}

            {!useShared && (
              <IntegrationFields
                provider={provider}
                draft={draft}
                showScopeNote
                onFieldChange={(key, value) => setField(draft.provider, key, value)}
                onReposChange={(key, repos) => setRepos(draft.provider, key, repos)}
                onOAuthConnected={({ refreshToken, clientId, clientSecret }) => {
                  setFields(draft.provider, { refreshToken, clientId, clientSecret });
                }}
              />
            )}
          </div>
        );
      })}

      {available.length > 0 && (
        <div className="flex flex-col gap-2">
          <div className="font-medium text-[0.844rem]" style={{ color: "var(--ink)" }}>
            Add an integration
          </div>
          <div className="flex flex-wrap gap-2">
            {available.map((p) => (
              <button
                key={p.id}
                type="button"
                className="af-btn af-btn-sm flex items-center gap-1.5"
                onClick={() => addProvider(p.id)}
              >
                <PlusIcon size={14} /> {p.label}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
