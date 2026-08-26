"use client";

import { useState } from "react";

import { AgentConfigurationSection } from "./agent-configuration-section";
import { IntegrationsStep } from "./hire-dialog-steps";
import { useAgentApplyAndRestart } from "../hooks/use-agent-apply-and-restart";
import { useUpdateAgent } from "../hooks/use-update-agent";
import type { Agent } from "../schemas";
import {
  coerceBooleanFields,
  expandGithubContent,
  hasIncompleteIntegration,
  type IntegrationDraft,
} from "../integrations";

export function AgentKeysSettings({ agent, canEdit, editing, onEdit }: {
  agent: Agent;
  canEdit: boolean;
  editing: boolean;
  onEdit: () => void;
}) {
  const updateAgent = useUpdateAgent();
  const [secretDrafts, setSecretDrafts] = useState<IntegrationDraft[]>([]);
  const [removedProviders, setRemovedProviders] = useState<string[]>([]);
  const { applyAndRestart } = useAgentApplyAndRestart(agent);
  const configuredSecrets = agent.secrets ?? [];
  const credentialError = updateAgent.error instanceof Error
    ? updateAgent.error.message
    : updateAgent.error
      ? "Save failed"
      : null;
  const hasChanges = secretDrafts.length > 0 || removedProviders.length > 0;

  async function applyChanges() {
    if (!hasChanges || hasIncompleteIntegration(secretDrafts)) return;
    const draftProviders = new Set(secretDrafts.map((draft) => draft.provider));
    const manualDrafts = secretDrafts.filter((draft) => !draft.sharedCredentialId);
    const sharedDrafts = secretDrafts.filter((draft) => Boolean(draft.sharedCredentialId));

    await applyAndRestart(() => updateAgent.mutateAsync({
      agentId: agent.id,
      secrets: manualDrafts.map((draft) => ({
        provider: draft.provider,
        content: coerceBooleanFields(
          draft.provider === "github" ? expandGithubContent(draft.content) : draft.content,
        ),
      })),
      sharedCredentials: sharedDrafts.map((draft) => ({ sharedCredentialId: draft.sharedCredentialId! })),
      removedSecretProviders: removedProviders.filter((provider) => !draftProviders.has(provider)),
    }).then(() => undefined));

    setSecretDrafts([]);
    setRemovedProviders([]);
  }

  function cancelChanges() {
    setSecretDrafts([]);
    setRemovedProviders([]);
    updateAgent.reset();
    onEdit();
  }

  return (
    <AgentConfigurationSection
      title="Keys & integrations"
      description="Runtime integration credentials are separate from communication connection credentials. Secret values remain write-only and encrypted at rest."
      canEdit={canEdit}
      editing={editing}
      onEdit={onEdit}
      onApply={applyChanges}
      onCancel={cancelChanges}
      onApplied={onEdit}
      applyDisabled={!hasChanges || hasIncompleteIntegration(secretDrafts) || updateAgent.isPending}
      restartOnApply={agent.status === "RUNNING"}
    >
      {!editing || !canEdit ? (
        <div className="flex flex-col gap-3">
          {configuredSecrets.length > 0 ? configuredSecrets.map((secret) => (
            <div key={secret.provider} className="flex items-center justify-between gap-3 rounded-xl px-3.5 py-3" style={{ border: "1px solid var(--line)" }}>
              <span className="font-medium text-[0.86rem]" style={{ color: "var(--ink-2)" }}>{secret.secretName}</span>
              <span className="text-[0.78rem]" style={{ color: "var(--ink-4)" }}>{secret.sharedCredentialName ? `Shared · ${secret.sharedCredentialName}` : "Configured · value hidden"}</span>
            </div>
          )) : <p className="m-0 text-[0.84rem]" style={{ color: "var(--ink-4)" }}>No integration credentials are configured.</p>}
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          {configuredSecrets.map((secret) => {
            const removed = removedProviders.includes(secret.provider);
            return (
              <div key={secret.provider} className="flex items-center justify-between gap-3 rounded-xl px-3.5 py-3" style={{ border: removed ? "1px dashed var(--line)" : "1px solid var(--line)", opacity: removed ? 0.55 : 1 }}>
                <div>
                  <div className="font-medium text-[0.86rem]" style={{ color: "var(--ink-2)" }}>{secret.secretName}</div>
                  <div className="text-[0.76rem]" style={{ color: "var(--ink-4)" }}>{removed ? "Will be removed" : secret.sharedCredentialName ? `Shared · ${secret.sharedCredentialName}` : "Value hidden"}</div>
                </div>
                <button type="button" className="af-btn af-btn-sm af-btn-ghost" onClick={() => setRemovedProviders((current) => removed ? current.filter((provider) => provider !== secret.provider) : [...current, secret.provider])}>{removed ? "Undo" : "Remove"}</button>
              </div>
            );
          })}
          <IntegrationsStep
            integrations={secretDrafts}
            onChange={setSecretDrafts}
            credentialError={credentialError}
          />
        </div>
      )}
    </AgentConfigurationSection>
  );
}
