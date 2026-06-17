"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import type { Agent } from "../schemas";
import { useAgentTemplate } from "../hooks/use-agent-template";
import { useUpdateAgent } from "../hooks/use-update-agent";
import { useDeleteAgent } from "../hooks/use-delete-agent";
import { XIcon, LockIcon } from "@/components/icons";
import { TokenInput } from "./hire-dialog-primitives";
import { MODELS, IntegrationsStep, TemplateSourceBadge, VersionSelect } from "./hire-dialog-steps";
import {
  getIntegrationProvider,
  hasIncompleteIntegration,
  type IntegrationDraft,
} from "../integrations";
import { SlackConfigPanel } from "./slack-config-panel";
import { useTemplates } from "../hooks/use-templates";
import { useTemplateVersions } from "../hooks/use-template-versions";

interface ConfigDrawerProps {
  agent: Agent;
  activeTab: TabKey;
  onTabChange: (tab: TabKey) => void;
  onClose: () => void;
}

function getTabs(platform: "slack" | "teams"): [string, string, boolean][] {
  return [
    ["personality", "Template", true],
    ["secrets", "Keys", true],
    ...(platform === "slack" ? [["channels", "Channels", true] as [string, string, boolean]] : []),
    ...(platform === "teams" ? [["endpoint", "Endpoint", true] as [string, string, boolean]] : []),
    ["skills", "Skills", false],
    ["k8s", "Infrastructure", false],
    ["danger", "Danger zone", true],
  ];
}

export type TabKey = "personality" | "channels" | "endpoint" | "skills" | "secrets" | "k8s" | "danger";

export const DRAWER_TAB_KEYS: TabKey[] = [
  "personality",
  "channels",
  "endpoint",
  "skills",
  "secrets",
  "k8s",
  "danger",
];

export function ConfigDrawer({ agent, activeTab, onTabChange, onClose }: ConfigDrawerProps) {
  const router = useRouter();
  // Current pinned template — used to show its display name next to the pin.
  const { template } = useAgentTemplate(agent.id, agent.templateVersion);
  const updateAgent = useUpdateAgent();
  const deleteAgent = useDeleteAgent();

  const [retireConfirm, setRetireConfirm] = useState(false);
  const [name, setName] = useState(agent.name);
  const [model, setModel] = useState(agent.model);
  const [saved, setSaved] = useState(false);
  // Template re-pin browsing state.
  const [templateSearch, setTemplateSearch] = useState("");
  const [repinSlug, setRepinSlug] = useState<string | null>(null);
  const [repinVersion, setRepinVersion] = useState<number | null>(null);
  const [savedTemplate, setSavedTemplate] = useState(false);
  const [slackAppToken, setSlackAppToken] = useState("");
  const [slackBotToken, setSlackBotToken] = useState("");
  const [showAppToken, setShowAppToken] = useState(false);
  const [showBotToken, setShowBotToken] = useState(false);
  const [teamsAppId, setTeamsAppId] = useState("");
  const [teamsAppPassword, setTeamsAppPassword] = useState("");
  const [showTeamsAppPassword, setShowTeamsAppPassword] = useState(false);
  const [teamsTenantId, setTeamsTenantId] = useState("");
  const [savedTokens, setSavedTokens] = useState(false);
  const [secretDrafts, setSecretDrafts] = useState<IntegrationDraft[]>([]);
  const [removedProviders, setRemovedProviders] = useState<string[]>([]);
  const [savedSecrets, setSavedSecrets] = useState(false);

  const tabs = getTabs(agent.platform);
  // Clamp the URL-provided tab to one that's actually reachable for this agent
  // (e.g. a deep-linked ?configTab=channels on a Teams agent falls back).
  const enabledKeys = tabs
    .filter(([, , enabled]) => enabled)
    .map(([k]) => k as TabKey);
  const tab: TabKey = enabledKeys.includes(activeTab) ? activeTab : "personality";

  const configuredSecrets = (agent.secrets ?? []).filter(
    (s) => !removedProviders.includes(s.provider),
  );

  const isRunning = agent.status === "RUNNING";

  // Template browse + re-pin.
  const { templates: browseTemplates } = useTemplates({
    search: templateSearch || undefined,
  });
  const { versions: repinVersions, isLoading: repinVersionsLoading } =
    useTemplateVersions(repinSlug);
  const resolvedRepinVersion =
    repinVersion ?? repinVersions[0]?.version ?? null;
  const repinIsNoop =
    repinSlug === agent.templateSlug &&
    resolvedRepinVersion === agent.templateVersion;

  async function handleSave() {
    try {
      await updateAgent.mutateAsync({ agentId: agent.id, name, model });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch {
      // error displayed via updateAgent.error
    }
  }

  async function handleApplyTemplate() {
    if (!repinSlug || resolvedRepinVersion == null) return;
    try {
      await updateAgent.mutateAsync({
        agentId: agent.id,
        templateSlug: repinSlug,
        templateVersion: resolvedRepinVersion,
      });
      setRepinSlug(null);
      setRepinVersion(null);
      setSavedTemplate(true);
      setTimeout(() => setSavedTemplate(false), 2500);
    } catch {
      // error displayed via updateAgent.error
    }
  }

  async function handleSaveTokens() {
    updateAgent.reset();
    try {
      if (agent.platform === "teams") {
        await updateAgent.mutateAsync({
          agentId: agent.id,
          ...(teamsAppId.trim() ? { teamsAppId } : {}),
          ...(teamsAppPassword.trim() ? { teamsAppPassword } : {}),
          ...(teamsTenantId.trim() ? { teamsTenantId } : {}),
        });
      } else {
        await updateAgent.mutateAsync({
          agentId: agent.id,
          ...(slackAppToken.trim() ? { slackAppToken } : {}),
          ...(slackBotToken.trim() ? { slackBotToken } : {}),
        });
      }
      setSavedTokens(true);
      setTimeout(() => setSavedTokens(false), 2000);
    } catch {
      // error displayed via updateAgent.error
    }
  }

  async function handleSaveSecrets() {
    updateAgent.reset();
    try {
      // If a provider is both re-added (draft) and removed, treat it as a
      // replace — the upsert wins (the backend rejects a provider in both lists).
      const draftProviders = new Set(secretDrafts.map((d) => d.provider));
      await updateAgent.mutateAsync({
        agentId: agent.id,
        secrets: secretDrafts.map((d) => ({
          provider: d.provider,
          content: d.content,
        })),
        removedSecretProviders: removedProviders.filter(
          (p) => !draftProviders.has(p),
        ),
      });
      setSecretDrafts([]);
      setRemovedProviders([]);
      setSavedSecrets(true);
      setTimeout(() => setSavedSecrets(false), 2000);
    } catch {
      // error displayed via updateAgent.error
    }
  }

  async function handleRetire() {
    try {
      await deleteAgent.mutateAsync(agent.id);
      router.push("/dashboard");
    } catch {
      // error displayed via deleteAgent.error
    }
  }

  return (
    <div className="fixed inset-0 z-50">
      <div
        className="absolute inset-0"
        style={{ background: "rgba(20,16,10,.4)" }}
        onClick={onClose}
      />
      <aside
        className="absolute top-0 right-0 bottom-0 flex flex-col af-drawer-panel"
        style={{ width: "min(36.25rem, 95vw)", background: "var(--bg)", boxShadow: "var(--shadow-pop)" }}
      >
        <header className="px-6.5 pt-5.5 pb-3.5 flex items-start justify-between">
          <div>
            <div
              className="text-xs uppercase tracking-[0.08em] font-semibold mb-1"
              style={{ color: "var(--ink-3)" }}
            >
              {agent.name} · configuration
            </div>
            <h2 className="text-2xl font-semibold tracking-tight m-0" style={{ color: "var(--ink)" }}>
              Configure agent
            </h2>
          </div>
          <button className="af-btn af-btn-ghost af-btn-icon" onClick={onClose}>
            <XIcon />
          </button>
        </header>

        <nav
          className="flex gap-0.5 px-4.5 pt-1 overflow-x-auto flex-shrink-0 no-scrollbar"
          style={{ borderBottom: "1px solid var(--line)" }}
        >
          {tabs.map(([k, l, enabled]) => (
            <button
              key={k}
              className="af-drawer-tab"
              data-active={tab === k}
              disabled={!enabled}
              onClick={() => enabled && onTabChange(k as TabKey)}
              style={!enabled ? { opacity: 0.35, cursor: "default" } : undefined}
            >
              {l}
            </button>
          ))}
        </nav>

        {isRunning && (
          <div
            className="px-6.5 py-2.5 text-[0.8125rem] font-medium flex items-center gap-2 flex-shrink-0"
            style={{
              background: "var(--accent-soft)",
              borderBottom: "1px solid var(--line)",
              borderLeft: "3px solid var(--accent-color)",
              color: "var(--accent-ink)",
            }}
          >
            <span
              className="w-1.5 h-1.5 rounded-full inline-block flex-shrink-0 af-dot-pulse"
              style={{ background: "var(--accent-color)" }}
              aria-hidden
            />
            <LockIcon size={13} />
            <span>Agent is running — <strong>stop it</strong> before making changes.</span>
          </div>
        )}

        <div className="flex-1 overflow-y-auto px-6.5 py-5.5 flex flex-col">
          {tab === "personality" && (
            <div className="flex flex-col flex-1 gap-5">
              <div className="flex flex-col gap-3.5">
                <div className="flex flex-col gap-1.5">
                  <label className="font-medium text-[0.844rem]" style={{ color: "var(--ink)" }}>Name</label>
                  <input
                    className="af-input"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    disabled={isRunning}
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <label className="font-medium text-[0.844rem]" style={{ color: "var(--ink)" }}>Model</label>
                  <select
                    className="af-input"
                    value={model}
                    onChange={(e) => setModel(e.target.value)}
                    disabled={isRunning}
                  >
                    {MODELS.map((m) => (
                      <option key={m.value} value={m.value}>{m.label}</option>
                    ))}
                  </select>
                </div>
                <div className="flex gap-2 items-center">
                  <button
                    className="af-btn af-btn-sm"
                    disabled={isRunning || updateAgent.isPending}
                    title={isRunning ? "Stop the agent before saving changes" : undefined}
                    onClick={() => { void handleSave(); }}
                  >
                    {updateAgent.isPending ? "Saving…" : saved ? "Saved!" : "Save name & model"}
                  </button>
                </div>
              </div>

              <div className="h-px" style={{ background: "var(--line)" }} />

              <div className="flex flex-col gap-1">
                <div className="font-medium text-[0.844rem]" style={{ color: "var(--ink)" }}>Template</div>
                <div className="text-[0.8125rem]" style={{ color: "var(--ink-3)" }}>
                  Currently pinned to{" "}
                  <span className="font-mono">{agent.templateSlug}@v{agent.templateVersion}</span>
                  {template?.templateName ? ` · ${template.templateName}` : ""}.
                  {" "}Re-pin to a different template or version. Edit content in Settings → Templates.
                </div>
              </div>

              <Hint>
                Browse templates, pick a version, and apply to change {agent.name}&apos;s persona.
              </Hint>

              <input
                className="af-input"
                placeholder="Search templates…"
                aria-label="Search templates"
                value={templateSearch}
                onChange={(e) => setTemplateSearch(e.target.value)}
                disabled={isRunning}
              />

              <div
                className="flex flex-col rounded-xl overflow-hidden"
                style={{ border: "1px solid var(--line)" }}
              >
                {browseTemplates.length === 0 ? (
                  <div className="px-3.5 py-3 text-[0.8125rem]" style={{ color: "var(--ink-3)" }}>
                    No templates match.
                  </div>
                ) : (
                  browseTemplates.map((t) => {
                    const selected = repinSlug === t.templateSlug;
                    return (
                      <button
                        key={t.templateSlug}
                        type="button"
                        disabled={isRunning}
                        className="flex items-center gap-2 px-3.5 py-2.5 text-left"
                        style={{
                          borderBottom: "1px solid var(--line)",
                          background: selected ? "var(--bg-soft)" : "transparent",
                        }}
                        onClick={() => { setRepinSlug(t.templateSlug); setRepinVersion(null); }}
                      >
                        <span className="font-medium text-[0.844rem]" style={{ color: "var(--ink)" }}>
                          {t.templateName}
                        </span>
                        <span className="font-mono text-[12px]" style={{ color: "var(--ink-4)" }}>
                          {t.templateSlug}
                        </span>
                        <TemplateSourceBadge source={t.templateSource} />
                      </button>
                    );
                  })
                )}
              </div>

              {repinSlug && (
                <div className="flex items-center gap-3">
                  <label className="text-[0.844rem] font-medium" style={{ color: "var(--ink-2)" }}>
                    Version
                  </label>
                  {repinVersionsLoading ? (
                    <span className="text-[0.8125rem]" style={{ color: "var(--ink-3)" }}>Loading…</span>
                  ) : (
                    <div className="w-40">
                      <VersionSelect
                        versions={repinVersions}
                        selectedVersion={resolvedRepinVersion}
                        onChange={setRepinVersion}
                        disabled={isRunning}
                      />
                    </div>
                  )}
                </div>
              )}

              <div className="flex gap-2 items-center">
                <button
                  className="af-btn af-btn-sm"
                  disabled={isRunning || updateAgent.isPending || !repinSlug || repinIsNoop}
                  title={isRunning ? "Stop the agent before changing its template" : undefined}
                  onClick={() => { void handleApplyTemplate(); }}
                >
                  {savedTemplate ? "Applied!" : "Apply template"}
                </button>
                {updateAgent.error && (
                  <span className="text-xs" style={{ color: "var(--err)" }}>
                    {updateAgent.error instanceof Error ? updateAgent.error.message : "Update failed"}
                  </span>
                )}
              </div>
            </div>
          )}

          {tab === "channels" && (
            <div>
              <Hint>Configure which Slack channels and users {agent.name} can interact with.</Hint>
              <SlackConfigPanel agent={agent} />
            </div>
          )}

          {tab === "skills" && (
            <div
              className="flex flex-col items-center justify-center text-center py-14 rounded-2xl"
              style={{ border: "1px dashed var(--line-strong)" }}
            >
              <div className="text-2xl mb-2">🚧</div>
              <div className="font-medium text-sm mb-1" style={{ color: "var(--ink)" }}>Coming soon</div>
              <div className="text-[0.8125rem]" style={{ color: "var(--ink-3)" }}>Skill management will appear here soon.</div>
            </div>
          )}

          {tab === "secrets" && agent.platform === "slack" && (
            <div className="flex flex-col gap-4">
              <Hint>
                Tokens are write-only — leave a field blank to keep the existing value.
              </Hint>
              <div className="flex flex-col gap-3.5">
                <div className="flex flex-col gap-1.5">
                  <label className="font-medium text-[0.844rem]" style={{ color: "var(--ink)" }}>App-level token</label>
                  <TokenInput
                    value={slackAppToken}
                    onChange={setSlackAppToken}
                    visible={showAppToken}
                    onToggle={() => setShowAppToken((v) => !v)}
                    placeholder="xapp-1-… (leave blank to keep existing)"
                    disabled={isRunning}
                  />
                  <span className="text-xs" style={{ color: "var(--ink-4)" }}>Starts with xapp- · required for Socket Mode</span>
                </div>
                <div className="flex flex-col gap-1.5">
                  <label className="font-medium text-[0.844rem]" style={{ color: "var(--ink)" }}>Bot token</label>
                  <TokenInput
                    value={slackBotToken}
                    onChange={setSlackBotToken}
                    visible={showBotToken}
                    onToggle={() => setShowBotToken((v) => !v)}
                    placeholder="xoxb-… (leave blank to keep existing)"
                    disabled={isRunning}
                  />
                  <span className="text-xs" style={{ color: "var(--ink-4)" }}>Starts with xoxb- · required for API calls</span>
                </div>
              </div>
              <div className="flex gap-2 items-center">
                <button
                  className="af-btn af-btn-sm"
                  disabled={isRunning || updateAgent.isPending || (!slackAppToken.trim() && !slackBotToken.trim())}
                  onClick={() => { void handleSaveTokens(); }}
                >
                  {updateAgent.isPending ? "Saving…" : savedTokens ? "Saved!" : "Save tokens"}
                </button>
                {updateAgent.error && (
                  <span className="text-xs" style={{ color: "var(--err)" }}>
                    {updateAgent.error instanceof Error ? updateAgent.error.message : "Save failed"}
                  </span>
                )}
              </div>
            </div>
          )}

          {tab === "secrets" && agent.platform === "teams" && (
            <div className="flex flex-col gap-4">
              <Hint>
                Credentials are write-only — leave a field blank to keep the existing value.
              </Hint>
              <div className="flex flex-col gap-3.5">
                <div className="flex flex-col gap-1.5">
                  <label className="font-medium text-[0.844rem]" style={{ color: "var(--ink)" }}>App (client) ID</label>
                  <input
                    className="af-input font-mono text-[0.8125rem]"
                    value={teamsAppId}
                    onChange={(e) => setTeamsAppId(e.target.value)}
                    placeholder="Leave blank to keep existing"
                    disabled={isRunning}
                  />
                  <span className="text-xs" style={{ color: "var(--ink-4)" }}>From your Azure Bot registration</span>
                </div>
                <div className="flex flex-col gap-1.5">
                  <label className="font-medium text-[0.844rem]" style={{ color: "var(--ink)" }}>App password (client secret)</label>
                  <TokenInput
                    value={teamsAppPassword}
                    onChange={setTeamsAppPassword}
                    visible={showTeamsAppPassword}
                    onToggle={() => setShowTeamsAppPassword((v) => !v)}
                    placeholder="Leave blank to keep existing"
                    disabled={isRunning}
                  />
                  <span className="text-xs" style={{ color: "var(--ink-4)" }}>Created in Azure App Registration → Certificates &amp; secrets</span>
                </div>
                <div className="flex flex-col gap-1.5">
                  <label className="font-medium text-[0.844rem]" style={{ color: "var(--ink)" }}>Tenant ID</label>
                  <input
                    className="af-input font-mono text-[0.8125rem]"
                    value={teamsTenantId}
                    onChange={(e) => setTeamsTenantId(e.target.value)}
                    placeholder="Leave blank to keep existing"
                    disabled={isRunning}
                  />
                  <span className="text-xs" style={{ color: "var(--ink-4)" }}>Found in Azure Portal → Azure Active Directory → Overview</span>
                </div>
              </div>
              <div className="flex gap-2 items-center">
                <button
                  className="af-btn af-btn-sm"
                  disabled={isRunning || updateAgent.isPending || (!teamsAppId.trim() && !teamsAppPassword.trim() && !teamsTenantId.trim())}
                  onClick={() => { void handleSaveTokens(); }}
                >
                  {updateAgent.isPending ? "Saving…" : savedTokens ? "Saved!" : "Save credentials"}
                </button>
                {updateAgent.error && (
                  <span className="text-xs" style={{ color: "var(--err)" }}>
                    {updateAgent.error instanceof Error ? updateAgent.error.message : "Save failed"}
                  </span>
                )}
              </div>
            </div>
          )}

          {tab === "secrets" && (
            <div className="flex flex-col gap-4 mt-6 pt-6" style={{ borderTop: "1px solid var(--line)" }}>
              <div className="font-semibold text-[0.9375rem]" style={{ color: "var(--ink)" }}>
                Integrations
              </div>
              <Hint>
                Credentials for the aai-cli tool (Jira, Confluence, GitHub, Bitbucket). Write-only —
                to change one, re-enter its fields below.
              </Hint>

              {configuredSecrets.length > 0 && (
                <div className="flex flex-col gap-2">
                  {configuredSecrets.map((s) => {
                    const label = getIntegrationProvider(s.provider)?.label ?? s.provider;
                    return (
                      <div
                        key={s.provider}
                        className="flex items-center justify-between p-3 rounded-2xl"
                        style={{ border: "1px solid var(--line)", background: "var(--bg-soft)" }}
                      >
                        <div className="flex flex-col">
                          <span className="font-semibold text-[0.844rem]" style={{ color: "var(--ink)" }}>
                            {label}
                          </span>
                          <span className="text-xs" style={{ color: "var(--ink-4)" }}>
                            {s.secretName} · configured
                          </span>
                        </div>
                        <button
                          className="af-btn af-btn-ghost af-btn-sm"
                          disabled={isRunning}
                          onClick={() => setRemovedProviders((r) => [...r, s.provider])}
                        >
                          Remove
                        </button>
                      </div>
                    );
                  })}
                </div>
              )}

              <div
                style={{
                  opacity: isRunning ? 0.5 : 1,
                  pointerEvents: isRunning ? "none" : "auto",
                }}
              >
                <IntegrationsStep
                  integrations={secretDrafts}
                  onChange={setSecretDrafts}
                />
              </div>

              <div className="flex gap-2 items-center">
                <button
                  className="af-btn af-btn-sm"
                  disabled={
                    isRunning ||
                    updateAgent.isPending ||
                    hasIncompleteIntegration(secretDrafts) ||
                    (secretDrafts.length === 0 && removedProviders.length === 0)
                  }
                  onClick={() => { void handleSaveSecrets(); }}
                >
                  {updateAgent.isPending ? "Saving…" : savedSecrets ? "Saved!" : "Save integrations"}
                </button>
                {updateAgent.error && (
                  <span className="text-xs" style={{ color: "var(--err)" }}>
                    {updateAgent.error instanceof Error ? updateAgent.error.message : "Save failed"}
                  </span>
                )}
              </div>
            </div>
          )}

          {tab === "endpoint" && (
            <div>
              <Hint>
                This is the messaging endpoint URL. Configure it in your Azure Bot registration under Configuration.
              </Hint>
              {agent.webhookUrl && (
                <div
                  className="flex items-center gap-2 p-4 rounded-xl font-mono text-sm"
                  style={{ background: "var(--bg-soft)", border: "1px solid var(--line)" }}
                >
                  <span className="flex-1 break-all" style={{ color: "var(--ink-2)" }}>
                    {agent.webhookUrl}
                  </span>
                  <button
                    className="af-btn af-btn-sm flex-shrink-0"
                    onClick={() => void navigator.clipboard.writeText(agent.webhookUrl!)}
                  >
                    Copy
                  </button>
                </div>
              )}
            </div>
          )}

          {tab === "k8s" && (
            <div>
              <Hint>
                Behind the scenes, {agent.name} is a set of standard Kubernetes resources. You usually don&apos;t need to touch these.
              </Hint>
              {[
                ["Deployment", `agent-${agent.id}`, "1/1 ready"],
                ["Service", `agent-${agent.id}-svc`, agent.platform === "teams" ? "ClusterIP · :8080, :3978" : "ClusterIP · :8080"],
                ["PersistentVolumeClaim", `agent-${agent.id}-workspace`, "Bound · 10Gi"],
                ["ConfigMap", `agent-${agent.id}-config`, "8 keys"],
                ["Secret", `agent-${agent.id}-secret`, agent.platform === "teams" ? "5 keys · encrypted" : "4 keys · encrypted"],
                ["NetworkPolicy", `agent-${agent.id}-egress`, "proxy + litellm only"],
              ].map(([kind, name, status]) => (
                <div
                  key={kind}
                  className="px-3.5 py-3 rounded-xl mb-1.5"
                  style={{ border: "1px solid var(--line)" }}
                >
                  <div className="font-mono text-[0.719rem]" style={{ color: "var(--ink-4)" }}>{kind}</div>
                  <div className="font-mono text-[0.8125rem] font-medium" style={{ color: "var(--ink)" }}>{name}</div>
                  <div className="text-[0.781rem]" style={{ color: "var(--ink-3)" }}>{status}</div>
                </div>
              ))}
            </div>
          )}

          {tab === "danger" && (
            <div>
              <Hint>Permanent actions. Pause first if you&apos;re not sure.</Hint>
              <div className="flex gap-2 flex-wrap mt-2">
                <button className="af-btn">Restart agent</button>
                <button className="af-btn">Reset workspace</button>
                <button
                  className="af-btn"
                  style={{ borderColor: "var(--err)", color: "var(--err)" }}
                  onClick={() => setRetireConfirm(true)}
                >
                  Retire agent
                </button>
              </div>
              <div className="text-xs mt-2.5 leading-[1.5]" style={{ color: "var(--ink-4)" }}>
                Retiring permanently deletes all pods, volumes, and configuration.
              </div>
            </div>
          )}
        </div>
      </aside>

      {retireConfirm && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
          <div
            className="absolute inset-0"
            style={{ background: "rgba(20,16,10,.5)" }}
            onClick={() => setRetireConfirm(false)}
          />
          <div
            className="relative w-full max-w-sm rounded-2xl p-6 shadow-2xl"
            style={{ background: "var(--bg-elev)", border: "1px solid var(--line)" }}
          >
            <h3 className="text-[1.0625rem] font-semibold tracking-tight mb-1.5" style={{ color: "var(--ink)" }}>
              Retire {agent.name}?
            </h3>
            <p className="text-[0.844rem] leading-[1.55] mb-6" style={{ color: "var(--ink-3)" }}>
              This will permanently delete {agent.name}&apos;s pods, volumes, and configuration. This cannot be undone.
            </p>
            <div className="flex gap-2 justify-end">
              <button className="af-btn af-btn-ghost" onClick={() => setRetireConfirm(false)}>
                Cancel
              </button>
              <button
                className="af-btn"
                disabled={deleteAgent.isPending}
                style={{ background: "var(--err)", borderColor: "var(--err)", color: "#fff" }}
                onClick={() => { void handleRetire(); }}
              >
                {deleteAgent.isPending ? "Retiring…" : "Retire agent"}
              </button>
            </div>
            {deleteAgent.error && (
              <p className="text-xs mt-3" style={{ color: "var(--err)" }}>
                {deleteAgent.error instanceof Error ? deleteAgent.error.message : "Retire failed"}
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function Hint({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="text-[0.8125rem] rounded-xl px-3.5 py-3 mb-4.5 leading-[1.5] flex items-start gap-1.5"
      style={{ background: "var(--bg-soft)", color: "var(--ink-3)" }}
    >
      {children}
    </div>
  );
}

