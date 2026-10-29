"use client";

import { useRef, useState } from "react";

import { useCustomApi } from "@/features/custom-api/hooks/use-custom-api";
import { ConnectionIntegrations } from "@/features/custom-api/components/connection-integrations";
import { connectionDraft, connectionPayload, type ConnectionDraft } from "@/features/custom-api/components/connection-drafts";

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
  const definition = getIntegrationProvider(provider);
  const name = definition?.label ?? provider;
  if (definition?.alwaysIsolated) {
    return { provider, secretName: name, isolation: { desired: true, switchAvailable: false, supportedModes: ["isolated"],
      ...definition.alwaysIsolated } };
  }
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
  const customApi = useCustomApi(agent.id, agent.status === "RUNNING");
  const [customDrafts, setCustomDrafts] = useState<ConnectionDraft[]>([]);
  const formRef = useRef<HTMLFormElement>(null);
  const updateAgent = useUpdateAgent();
  const isolation = useIntegrationIsolation(agent.id);
  const stopAgent = useStopAgent();
  const startAgent = useStartAgent();
  const [drafts, setDrafts] = useState<IntegrationDraft[]>(() => setupDrafts(agent));
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [restartRequired, setRestartRequired] = useState(false);
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
  const customChanges = customDrafts.filter((draft) => draft.changed);
  const removedConnections = (customApi.connections ?? []).filter((connection) => !customDrafts.some((draft) => draft.connection?.id === connection.id));
  const hasCustomChanges = customChanges.length > 0 || removedConnections.length > 0;
  const hasChanges = hasCustomChanges || hasCredentialChanges || changedPolicies.length > 0 || restartRequired || (failed && (drafts.length > 0 || customDrafts.length > 0));
  const pending = customApi.connectionMutation.isPending || customApi.batchMutation.isPending || saving || updateAgent.isPending || isolation.isPending || stopAgent.isPending || startAgent.isPending;
  const canRestart = agent.allowedActions.includes("agent.lifecycle.manage");
  const restart = restartRequired || agent.status === "RUNNING" || (failed && (drafts.length > 0 || customDrafts.length > 0));

  function beginEditing() {
    if (customApi.isLoadingConnections || customApi.connectionsError) return;
    setDrafts(setupDrafts(agent));
    setCustomDrafts((customApi.connections ?? []).map(connectionDraft));
    setSaveError(null);
    setRestartRequired(false);
    onEdit();
  }

  async function applyChanges() {
    if (!hasChanges || hasIncompleteIntegration(drafts)) return;
    if (!formRef.current?.reportValidity()) throw new Error("Complete the integration fields before applying.");
    setSaveError(null);
    setSaving(true);
    try {
      // A single policy change uses the server's complete preflight/restart flow.
      if (!hasCredentialChanges && changedPolicies.length === 0 && customChanges.length + removedConnections.length === 1) {
        const draft = customChanges[0];
        await customApi.connectionMutation.mutateAsync(draft
          ? { id: draft.connection?.id, data: connectionPayload(draft.value), restart }
          : { id: removedConnections[0].id, remove: true, restart });
      } else if (!hasCustomChanges && !hasCredentialChanges && changedPolicies.length <= 1) {
        const draft = changedPolicies[0] ?? drafts[0];
        if (draft) await isolation.mutateAsync({ provider: draft.provider, isolated: draft.isolated ?? false, restart });
        else if (restart) await startAgent.mutateAsync(agent.id);
      } else {
        const batch = {
          creates: customChanges.filter((draft) => !draft.connection).map((draft) => connectionPayload(draft.value)),
          updates: customChanges.flatMap((draft) => draft.connection ? [{ id: draft.connection.id, data: connectionPayload(draft.value) }] : []),
          deletes: removedConnections.map((connection) => connection.id),
          restart,
        };
        if (hasCustomChanges && !hasCredentialChanges && changedPolicies.length === 0) {
          await customApi.batchMutation.mutateAsync(batch);
        } else {
          // Reject invalid Custom API drafts before the shared provider workflow stops the Agent.
          if (hasCustomChanges) await customApi.preflight(batch);
          if (restart) setRestartRequired(true);
          if (agent.status === "RUNNING") await stopAgent.mutateAsync(agent.id);
          if (hasCustomChanges) {
            const saved = await customApi.batchMutation.mutateAsync({ ...batch, restart: false });
            setCustomDrafts(saved.data.map(connectionDraft));
          }
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
      }
      setRestartRequired(false);
      setCustomDrafts([]);
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : "Could not save the integration setup.");
      throw error;
    } finally {
      setSaving(false);
    }
  }

  return (
    <AgentConfigurationSection title="Integrations" description="Runtime integration credentials are separate from communication connection credentials. Secret values remain write-only and encrypted at rest."
      canEdit={canEdit && !customApi.isLoadingConnections && !customApi.connectionsError} editing={editing} onEdit={beginEditing} onApply={applyChanges}
      onCancel={() => { setCustomDrafts([]); setDrafts(setupDrafts(agent)); setSaveError(null); setRestartRequired(false); onEdit(); }} onApplied={onEdit}
      applyDisabled={customApi.isLoadingConnections || Boolean(customApi.connectionsError) || agent.updateInProgress || !hasChanges || hasIncompleteIntegration(drafts) || pending || (restart && !canRestart)} restartOnApply={restart}>
      {!editing || !canEdit ? (
        <div className="flex flex-col gap-3">
          {secrets.length > 0 ? secrets.map((secret) => (
            <div key={secret.provider} className="flex items-center justify-between gap-3 rounded-xl px-3.5 py-3" style={{ border: "1px solid var(--line)" }}>
              <span className="font-medium text-[0.86rem]" style={{ color: "var(--ink-2)" }}>{secret.secretName}</span>
              <span className="text-[0.78rem]" style={{ color: "var(--ink-4)" }}>{secret.source === "platform_default" ? "Platform default" : secret.sharedCredentialName ? `Shared · ${secret.sharedCredentialName}` : "Configured · value hidden"}</span>
            </div>
          )) : !customApi.connections?.length && <p className="m-0 text-[0.84rem]" style={{ color: "var(--ink-4)" }}>No integration credentials are configured.</p>}
          {customApi.connections?.map((connection) => <div key={connection.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border px-3.5 py-3"><span className="font-medium text-[0.86rem]">Custom API · {connection.name}</span><span className="text-[0.78rem] text-muted-foreground">{connection.isolated ? "Isolated" : "Direct credentials"} · {connection.pendingApply ? "Pending apply" : "Applied"}</span></div>)}
          {customApi.isLoadingConnections && <p role="status">Loading Custom API connections…</p>}
          {customApi.connectionsError && <div role="alert">Could not load Custom API connections. <button type="button" className="af-btn af-btn-sm" onClick={() => void customApi.refetchConnections()}>Retry</button></div>}
        </div>
      ) : (
        <div className="flex flex-col gap-4">
        {saveError && <p role="alert" className="m-0 text-sm" style={{ color: "var(--err)" }}>{saveError}</p>}
        {customApi.connectionsError && <div role="alert">Could not load Custom API connections. Cancel and retry before editing.</div>}
        <form ref={formRef} onInvalidCapture={(event) => { const details = (event.target as HTMLElement).closest("details"); if (details) details.open = true; }} onSubmit={(event) => event.preventDefault()}>
        <fieldset disabled={pending || customApi.isLoadingConnections || Boolean(customApi.connectionsError)} className="m-0 min-w-0 border-0 p-0">
        <IntegrationsStep agentId={agent.id}
          onAddCustomApi={() => setCustomDrafts((current) => [...current, connectionDraft()])}
          extraIntegrations={<ConnectionIntegrations agent={agent} drafts={customDrafts} onChange={setCustomDrafts} />} integrations={drafts} onChange={(next) => setDrafts(next.map((draft) => ({ ...draft, isolated: draft.isolated ?? savedSecret(draft)?.isolation?.desired ?? newSecret(draft.provider).isolation?.desired ?? false })))}
          canRemoveProvider={(provider) => provider !== "sharepoint" || (!sharepointAccess.isPending && !sharepointAccess.isError && sharepointAccess.data?.mode !== "selected_sites")}
          renderIsolation={(draft) => <IntegrationIsolationControl agent={agent} secret={savedSecret(draft) ?? newSecret(draft.provider)}
            isolated={draft.isolated ?? false} onChange={(isolated) => setDrafts((current) => current.map((item) => item.provider === draft.provider ? { ...item, isolated } : item))} />} />
        </fieldset>
        </form>
        </div>
      )}
    </AgentConfigurationSection>
  );
}
