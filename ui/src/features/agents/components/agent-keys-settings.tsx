"use client";

import { useState } from "react";

import { IntegrationsStep } from "./hire-dialog-steps";
import { TokenInput } from "./hire-dialog-primitives";
import { AgentConfigurationSection } from "./agent-configuration-section";
import { useAgentApplyAndRestart } from "../hooks/use-agent-apply-and-restart";
import { useUpdateAgent } from "../hooks/use-update-agent";
import { useValidateIntegration } from "../hooks/use-validate-integration";
import type { Agent, IntegrationValidationResult } from "../schemas";
import {
  coerceBooleanFields,
  expandGithubContent,
  hasIncompleteIntegration,
  type IntegrationDraft,
} from "../integrations";

function ValidationDetails({
  result,
  error,
}: {
  result?: IntegrationValidationResult;
  error?: string;
}) {
  if (!result && !error) return null;

  return (
    <div className="flex flex-col gap-1 text-[0.76rem]" style={{ color: "var(--ink-3)" }}>
      {error && <span style={{ color: "var(--err)" }}>{error}</span>}
      {result && (
        <>
          <span>
            Status: {result.validationStatus}
            {result.validationIdentity ? ` · ${result.validationIdentity}` : ""}
          </span>
          {result.validationError && <span style={{ color: "var(--err)" }}>{result.validationError}</span>}
          {result.missingScopes.length > 0 && (
            <span>Missing scopes: {result.missingScopes.join(", ")}</span>
          )}
        </>
      )}
    </div>
  );
}

export function AgentKeysSettings({
  agent,
  canEdit,
  editing,
  onEdit,
}: {
  agent: Agent;
  canEdit: boolean;
  editing: boolean;
  onEdit: () => void;
}) {
  const updateAgent = useUpdateAgent();
  const validateIntegration = useValidateIntegration();
  const [validationResults, setValidationResults] = useState<Record<string, IntegrationValidationResult>>({});
  const [validationErrors, setValidationErrors] = useState<Record<string, string>>({});
  const [validatingProvider, setValidatingProvider] = useState<string | null>(null);
  const [slackAppToken, setSlackAppToken] = useState("");
  const [slackBotToken, setSlackBotToken] = useState("");
  const [teamsAppId, setTeamsAppId] = useState("");
  const [teamsAppPassword, setTeamsAppPassword] = useState("");
  const [teamsTenantId, setTeamsTenantId] = useState("");
  const [telegramBotToken, setTelegramBotToken] = useState("");
  const [discordBotToken, setDiscordBotToken] = useState("");
  const [showSecret, setShowSecret] = useState(false);
  const [secretDrafts, setSecretDrafts] = useState<IntegrationDraft[]>([]);
  const [removedProviders, setRemovedProviders] = useState<string[]>([]);
  const { applyAndRestart } = useAgentApplyAndRestart(agent);

  const configuredSecrets = (agent.secrets ?? []).filter((secret) => secret.provider !== "slack");

  const hasPlatformChanges = Boolean(
    slackAppToken.trim() ||
      slackBotToken.trim() ||
      teamsAppId.trim() ||
      teamsAppPassword.trim() ||
      teamsTenantId.trim() ||
      telegramBotToken.trim() ||
      discordBotToken.trim(),
  );
  const hasIntegrationChanges = secretDrafts.length > 0 || removedProviders.length > 0;
  const hasChanges = hasPlatformChanges || hasIntegrationChanges;

  function validate(provider: string) {
    setValidatingProvider(provider);
    setValidationErrors((current) => {
      const next = { ...current };
      delete next[provider];
      return next;
    });
    validateIntegration.mutate(
      { agentId: agent.id, provider },
      {
        onSuccess: ({ provider: validatedProvider, result }) => {
          setValidationResults((current) => ({ ...current, [validatedProvider]: result }));
          setValidatingProvider(null);
        },
        onError: (error) => {
          setValidationErrors((current) => ({
            ...current,
            [provider]: error instanceof Error ? error.message : "Validation failed",
          }));
          setValidatingProvider(null);
        },
      },
    );
  }

  async function applyChanges() {
    if (!hasChanges || hasIncompleteIntegration(secretDrafts)) return;

    const draftProviders = new Set(secretDrafts.map((draft) => draft.provider));
    const manualDrafts = secretDrafts.filter((draft) => !draft.sharedCredentialId);
    const sharedDrafts = secretDrafts.filter((draft) => !!draft.sharedCredentialId);
    const platformPayload =
      agent.platform === "slack"
        ? {
            ...(slackAppToken.trim() ? { slackAppToken } : {}),
            ...(slackBotToken.trim() ? { slackBotToken } : {}),
          }
        : agent.platform === "teams"
          ? {
              ...(teamsAppId.trim() ? { teamsAppId } : {}),
              ...(teamsAppPassword.trim() ? { teamsAppPassword } : {}),
              ...(teamsTenantId.trim() ? { teamsTenantId } : {}),
            }
          : agent.platform === "telegram"
            ? { ...(telegramBotToken.trim() ? { telegramBotToken } : {}) }
            : { ...(discordBotToken.trim() ? { discordBotToken } : {}) };

    await applyAndRestart(() =>
      updateAgent.mutateAsync({
        agentId: agent.id,
        ...platformPayload,
        ...(manualDrafts.length > 0
          ? {
              secrets: manualDrafts.map((draft) => ({
                provider: draft.provider,
                content: coerceBooleanFields(
                  draft.provider === "github" ? expandGithubContent(draft.content) : draft.content,
                ),
              })),
            }
          : {}),
        ...(sharedDrafts.length > 0
          ? { sharedCredentials: sharedDrafts.map((draft) => ({ sharedCredentialId: draft.sharedCredentialId! })) }
          : {}),
        ...(hasIntegrationChanges
          ? { removedSecretProviders: removedProviders.filter((provider) => !draftProviders.has(provider)) }
          : {}),
      }).then(() => undefined),
    );

    setSlackAppToken("");
    setSlackBotToken("");
    setTeamsAppId("");
    setTeamsAppPassword("");
    setTeamsTenantId("");
    setTelegramBotToken("");
    setDiscordBotToken("");
    setSecretDrafts([]);
    setRemovedProviders([]);
  }

  function cancelChanges() {
    setSlackAppToken("");
    setSlackBotToken("");
    setTeamsAppId("");
    setTeamsAppPassword("");
    setTeamsTenantId("");
    setTelegramBotToken("");
    setDiscordBotToken("");
    setSecretDrafts([]);
    setRemovedProviders([]);
    updateAgent.reset();
    onEdit();
  }

  const platformConfigured =
    agent.platform === "slack"
      ? Boolean(agent.slackConfig)
      : agent.platform === "teams"
        ? Boolean(agent.teamsConfig)
        : agent.platform === "telegram"
          ? Boolean(agent.telegramConfig)
          : Boolean(agent.discordConfig);

  return (
    <AgentConfigurationSection
      title="Keys & integrations"
      description="Secret values are write-only. Existing credentials are shown as metadata and remain encrypted at rest."
      canEdit={canEdit}
      editing={editing}
      onEdit={onEdit}
      onApply={applyChanges}
      onCancel={cancelChanges}
      onApplied={onEdit}
      applyDisabled={
        !hasChanges ||
        hasIncompleteIntegration(secretDrafts) ||
        updateAgent.isPending
      }
      restartOnApply={agent.status === "RUNNING"}
    >
      {!editing || !canEdit ? (
        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between gap-3 rounded-xl px-3.5 py-3" style={{ border: "1px solid var(--line)", background: "var(--bg-soft)" }}>
            <div>
              <div className="font-medium text-[0.86rem]" style={{ color: "var(--ink-2)" }}>Platform credentials</div>
              <div className="text-[0.78rem]" style={{ color: "var(--ink-4)" }}>{platformConfigured ? "Configured · values hidden" : "Not configured"}</div>
            </div>
            <span className="font-mono text-[0.75rem] uppercase" style={{ color: "var(--ink-4)" }}>{agent.platform}</span>
          </div>
          {configuredSecrets.length > 0 ? (
            configuredSecrets.map((secret) => (
              <div key={secret.provider} className="flex flex-col gap-2 rounded-xl px-3.5 py-3" style={{ border: "1px solid var(--line)" }}>
                <div className="flex items-center justify-between gap-3">
                  <span className="font-medium text-[0.86rem]" style={{ color: "var(--ink-2)" }}>{secret.secretName}</span>
                  <div className="flex items-center gap-2">
                    <span className="text-[0.78rem]" style={{ color: "var(--ink-4)" }}>{secret.sharedCredentialName ? `Shared · ${secret.sharedCredentialName}` : "Configured · value hidden"}</span>
                    {canEdit && (
                      <button
                        type="button"
                        className="af-btn af-btn-sm af-btn-ghost"
                        onClick={() => validate(secret.provider)}
                        disabled={validatingProvider === secret.provider}
                      >
                        {validatingProvider === secret.provider ? "Validating…" : "Validate"}
                      </button>
                    )}
                  </div>
                </div>
                <ValidationDetails result={validationResults[secret.provider]} error={validationErrors[secret.provider]} />
              </div>
            ))
          ) : (
            <p className="m-0 text-[0.84rem]" style={{ color: "var(--ink-4)" }}>No integration credentials are configured.</p>
          )}
        </div>
      ) : (
        <div className="flex flex-col gap-7">
          <div className="flex flex-col gap-4">
            <div>
              <h3 className="m-0 text-[0.94rem] font-semibold" style={{ color: "var(--ink-2)" }}>Platform credentials</h3>
              <p className="mb-0 mt-1 text-[0.8rem]" style={{ color: "var(--ink-3)" }}>Leave fields blank to keep the existing value.</p>
            </div>

            {agent.platform === "slack" && (
              <>
                <label className="flex flex-col gap-1.5 text-[0.84rem] font-medium" style={{ color: "var(--ink)" }}>
                  App-level token
                  <TokenInput value={slackAppToken} onChange={setSlackAppToken} visible={showSecret} onToggle={() => setShowSecret((value) => !value)} placeholder="xapp-…" />
                </label>
                <label className="flex flex-col gap-1.5 text-[0.84rem] font-medium" style={{ color: "var(--ink)" }}>
                  Bot token
                  <TokenInput value={slackBotToken} onChange={setSlackBotToken} visible={showSecret} onToggle={() => setShowSecret((value) => !value)} placeholder="xoxb-…" />
                </label>
              </>
            )}
            {agent.platform === "teams" && (
              <>
                <label className="flex flex-col gap-1.5 text-[0.84rem] font-medium" style={{ color: "var(--ink)" }}>
                  App (client) ID
                  <input className="af-input font-mono text-[0.8125rem]" value={teamsAppId} onChange={(event) => setTeamsAppId(event.target.value)} placeholder="Leave blank to keep existing" />
                </label>
                <label className="flex flex-col gap-1.5 text-[0.84rem] font-medium" style={{ color: "var(--ink)" }}>
                  App password
                  <TokenInput value={teamsAppPassword} onChange={setTeamsAppPassword} visible={showSecret} onToggle={() => setShowSecret((value) => !value)} placeholder="Leave blank to keep existing" />
                </label>
                <label className="flex flex-col gap-1.5 text-[0.84rem] font-medium" style={{ color: "var(--ink)" }}>
                  Tenant ID
                  <input className="af-input font-mono text-[0.8125rem]" value={teamsTenantId} onChange={(event) => setTeamsTenantId(event.target.value)} placeholder="Leave blank to keep existing" />
                </label>
              </>
            )}
            {agent.platform === "telegram" && (
              <label className="flex flex-col gap-1.5 text-[0.84rem] font-medium" style={{ color: "var(--ink)" }}>
                Bot token
                <TokenInput value={telegramBotToken} onChange={setTelegramBotToken} visible={showSecret} onToggle={() => setShowSecret((value) => !value)} placeholder="123456:ABC-DEF…" />
              </label>
            )}
            {agent.platform === "discord" && (
              <label className="flex flex-col gap-1.5 text-[0.84rem] font-medium" style={{ color: "var(--ink)" }}>
                Discord bot token
                <TokenInput value={discordBotToken} onChange={setDiscordBotToken} visible={showSecret} onToggle={() => setShowSecret((value) => !value)} placeholder="Leave blank to keep existing token" />
              </label>
            )}
          </div>

          <div className="h-px" style={{ background: "var(--line)" }} />

          <div className="flex flex-col gap-4">
            <div>
              <h3 className="m-0 text-[0.94rem] font-semibold" style={{ color: "var(--ink-2)" }}>Integration credentials</h3>
              <p className="mb-0 mt-1 text-[0.8rem]" style={{ color: "var(--ink-3)" }}>Add, replace, or remove credentials independently from the platform token.</p>
            </div>
            {configuredSecrets.map((secret) => {
              const removed = removedProviders.includes(secret.provider);
              return (
                <div key={secret.provider} className="flex flex-col gap-2 rounded-xl px-3.5 py-3" style={{ border: removed ? "1px dashed var(--line)" : "1px solid var(--line)", opacity: removed ? 0.55 : 1 }}>
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="font-medium text-[0.86rem]" style={{ color: "var(--ink-2)" }}>{secret.secretName}</div>
                      <div className="text-[0.76rem]" style={{ color: "var(--ink-4)" }}>{removed ? "Will be removed" : secret.sharedCredentialName ? `Shared · ${secret.sharedCredentialName}` : "Value hidden"}</div>
                    </div>
                    <div className="flex items-center gap-2">
                      {canEdit && (
                        <button
                          type="button"
                          className="af-btn af-btn-sm af-btn-ghost"
                          onClick={() => validate(secret.provider)}
                          disabled={removed || validatingProvider === secret.provider}
                        >
                          {validatingProvider === secret.provider ? "Validating…" : "Validate"}
                        </button>
                      )}
                      <button type="button" className="af-btn af-btn-sm af-btn-ghost" onClick={() => setRemovedProviders((current) => removed ? current.filter((provider) => provider !== secret.provider) : [...current, secret.provider])}>{removed ? "Undo" : "Remove"}</button>
                    </div>
                  </div>
                  <ValidationDetails result={validationResults[secret.provider]} error={validationErrors[secret.provider]} />
                </div>
              );
            })}
            <IntegrationsStep integrations={secretDrafts} onChange={setSecretDrafts} />
            {updateAgent.error && <span className="text-xs" style={{ color: "var(--err)" }}>{updateAgent.error instanceof Error ? updateAgent.error.message : "Save failed"}</span>}
          </div>
        </div>
      )}
    </AgentConfigurationSection>
  );
}
