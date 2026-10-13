"use client";

import { useState } from "react";

import { AgentConfigurationSection } from "./agent-configuration-section";
import { IntegrationsStep } from "./hire-dialog-steps";
import { IntegrationIsolationControl } from "./integration-isolation-control";
import { useIntegrationIsolation } from "../hooks/use-integration-isolation";
import { useStartAgent } from "../hooks/use-start-agent";
import { useStopAgent } from "../hooks/use-stop-agent";
import { useSharePointAccess } from "../hooks/use-sharepoint-sign-in";
import { useUpdateAgent } from "../hooks/use-update-agent";
import type { Agent, AgentSecretRead } from "../schemas";
import { coerceBooleanFields, expandGithubContent, getIntegrationProvider, hasIncompleteIntegration, isSignInOnlyProvider, type IntegrationDraft } from "../integrations";

function setupDrafts(agent: Agent): IntegrationDraft[] {
  return (agent.secrets ?? []).map((secret) => ({ provider: secret.provider, content: {}, existing: true,
    sharedCredentialId: secret.sharedCredentialId ?? undefined,
    platformDefault: secret.source === "platform_default", isolated: secret.isolation?.desired ?? false }));
}

// New credentials have no server policy yet. Describe the credential boundary;
// the isolation endpoint validates runtime support after the credential is saved.
function newSecret(provider: string): AgentSecretRead {
  const name = getIntegrationProvider(provider)?.label ?? provider;
  const broker = provider === "google_workspace" || provider === "sharepoint";
  return { provider, secretName: name, isolation: { desired: false, switchAvailable: true, supportedModes: ["direct", "isolated"],
    directDescription: `This Agent receives the ${name} credentials and connects directly.`,
    isolatedDescription: broker
      ? `This Agent receives expiring access tokens only; renewable ${name} credentials stay outside it.`
      : `The ${name} credential stays outside this Agent; Agent Barn authenticates requests.` } };
}

export function AgentKeysSettings({ agent, canEdit, editing, onEdit }: {
  agent: Agent; canEdit: boolean; editing: boolean; onEdit: () => void;
}) {
  const updateAgent = useUpdateAgent();
  const isolation = useIntegrationIsolation(agent.id);
  const stopAgent = useStopAgent();
  const startAgent = useStartAgent();
  const [drafts, setDrafts] = useState<IntegrationDraft[]>(() => setupDrafts(agent));
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const secrets = agent.secrets ?? [];
  const sharepointAccess = useSharePointAccess(agent.id, {
    enabled: editing && secrets.some((secret) => secret.provider === "sharepoint"),
  });
  const removedProviders = secrets.filter((secret) => secret.source !== "platform_default" && !drafts.some((draft) => draft.provider === secret.provider)).map((secret) => secret.provider);
  const changedCredentials = drafts.filter((draft) => !draft.existing);
  function savedSecret(draft: IntegrationDraft) {
    return secrets.find((secret) => secret.provider === draft.provider && (secret.source === "platform_default") === Boolean(draft.platformDefault));
  }
  const changedPolicies = drafts.filter((draft) => (draft.isolated ?? false) !== (savedSecret(draft)?.isolation?.desired ?? false));
  const hasCredentialChanges = changedCredentials.length > 0 || removedProviders.length > 0;
  const failed = agent.status === "ERROR";
  const hasChanges = hasCredentialChanges || changedPolicies.length > 0 || (failed && drafts.length > 0);
  const pending = saving || updateAgent.isPending || isolation.isPending || stopAgent.isPending || startAgent.isPending;
  const canRestart = agent.allowedActions.includes("agent.lifecycle.manage");
  const restart = agent.status === "RUNNING" || (failed && drafts.length > 0);

  function beginEditing() {
    setDrafts(setupDrafts(agent));
    setSaveError(null);
    onEdit();
  }

  async function applyChanges() {
    if (!hasChanges || hasIncompleteIntegration(drafts)) return;
    setSaveError(null);
    setSaving(true);
    try {
      // A single policy change uses the server's complete preflight/restart flow.
      if (!hasCredentialChanges && changedPolicies.length <= 1) {
        const draft = changedPolicies[0] ?? drafts[0];
        if (!draft) return;
        await isolation.mutateAsync({ provider: draft.provider, isolated: draft.isolated ?? false, restart });
      } else {
        if (agent.status === "RUNNING") await stopAgent.mutateAsync(agent.id);
        if (hasCredentialChanges) {
          await updateAgent.mutateAsync({ agentId: agent.id,
            secrets: changedCredentials.filter((draft) => !draft.sharedCredentialId && !isSignInOnlyProvider(draft.provider)).map((draft) => ({ provider: draft.provider,
              content: coerceBooleanFields(draft.provider === "github" ? expandGithubContent(draft.content) : draft.content) })),
            sharedCredentials: changedCredentials.filter((draft) => draft.sharedCredentialId).map((draft) => ({ sharedCredentialId: draft.sharedCredentialId! })),
            removedSecretProviders: removedProviders });
        }
        for (const draft of changedPolicies) {
          await isolation.mutateAsync({ provider: draft.provider, isolated: draft.isolated ?? false, restart: false });
        }
        // A failed save leaves the Agent stopped; never boot with a partly saved choice.
        if (restart) await startAgent.mutateAsync(agent.id);
      }
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : "Could not save the integration setup.");
      throw error;
    } finally {
      setSaving(false);
    }
  }

  return (
    <AgentConfigurationSection title="Integrations" description="Runtime integration credentials are separate from communication connection credentials. Secret values remain write-only and encrypted at rest."
      canEdit={canEdit} editing={editing} onEdit={beginEditing} onApply={applyChanges}
      onCancel={() => { setDrafts(setupDrafts(agent)); setSaveError(null); onEdit(); }} onApplied={onEdit}
      applyDisabled={agent.updateInProgress || !hasChanges || hasIncompleteIntegration(drafts) || pending || (restart && !canRestart)} restartOnApply={restart}>
      {!editing || !canEdit ? (
        <div className="flex flex-col gap-3">
          {secrets.length > 0 ? secrets.map((secret) => (
            <div key={secret.provider} className="flex items-center justify-between gap-3 rounded-xl px-3.5 py-3" style={{ border: "1px solid var(--line)" }}>
              <span className="font-medium text-[0.86rem]" style={{ color: "var(--ink-2)" }}>{secret.secretName}</span>
              <span className="text-[0.78rem]" style={{ color: "var(--ink-4)" }}>{secret.source === "platform_default" ? "Platform default" : secret.sharedCredentialName ? `Shared · ${secret.sharedCredentialName}` : "Configured · value hidden"}</span>
            </div>
          )) : <p className="m-0 text-[0.84rem]" style={{ color: "var(--ink-4)" }}>No integration credentials are configured.</p>}
        </div>
      ) : (
        <div className="flex flex-col gap-4">
        {saveError && <p role="alert" className="m-0 text-sm" style={{ color: "var(--err)" }}>{saveError}</p>}
        <fieldset disabled={pending} className="m-0 min-w-0 border-0 p-0">
        <IntegrationsStep agentId={agent.id} integrations={drafts} onChange={(next) => setDrafts(next.map((draft) => ({ ...draft, isolated: draft.isolated ?? savedSecret(draft)?.isolation?.desired ?? false })))}
          canRemoveProvider={(provider) => provider !== "sharepoint" || (!sharepointAccess.isPending && !sharepointAccess.isError && sharepointAccess.data?.mode !== "selected_sites")}
          renderIsolation={(draft) => <IntegrationIsolationControl agent={agent} secret={savedSecret(draft) ?? newSecret(draft.provider)}
            isolated={draft.isolated ?? false} onChange={(isolated) => setDrafts((current) => current.map((item) => item.provider === draft.provider ? { ...item, isolated } : item))} />} />
        </fieldset>
        </div>
      )}
    </AgentConfigurationSection>
  );
}
