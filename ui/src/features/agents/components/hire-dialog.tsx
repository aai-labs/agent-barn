"use client";

import { useState, useEffect, useRef } from "react";
import { XIcon, CheckIcon } from "@/components/icons";
import { useSlackConfigToken } from "@/features/account/hooks/use-slack-config-token";
import { useSlackConfigTokenActions } from "@/features/account/hooks/use-slack-config-token-actions";
import { useCreateAgent } from "../hooks/use-create-agent";
import { useCreateSlackApp } from "../hooks/use-create-slack-app";
import { useStartAgent } from "../hooks/use-start-agent";
import { useTemplateVersions } from "../hooks/use-template-versions";
import { DialogShell } from "./hire-dialog-primitives";
import {
  WizardStep,TemplateStep, AgentTypeStep, PlatformChoiceStep, SlackChoiceStep,
  ConfigTokenStep, BotBuilderStep, SlackTokensStep,
  TeamsBotBuilderStep, TeamsCredentialsStep, DetailsStep, SkillsStep,
  downloadTeamsAppPackage, generateTeamsManifest,
} from "./hire-dialog-steps";
import { SlackConfigPanel } from "./slack-config-panel";
import {
  hasIncompleteIntegration,
  expandGithubContent,
  type IntegrationDraft,
} from "../integrations";
import type { Agent, AgentTemplateRead } from "../schemas";

const DEFAULT_AGENT_NAME = "Aria";
const DEFAULT_BOT_DESCRIPTION = "Handles tasks and reduces day-to-day friction.";

interface HireDialogProps {
  onClose: () => void;
  onHired: (info: { name: string; role: string }) => void;
}

const PROVISION_STEPS = [
  { at: 14, text: "Validating credentials" },
  { at: 32, text: "Creating agent profile" },
  { at: 50, text: "Saving persona and template" },
  { at: 68, text: "Encrypting and storing tokens" },
  { at: 84, text: "Saving integrations" },
  { at: 96, text: "", isPending: true },
];

function getSteps(
  agentType: "openclaw" | "hermes",
  platform: "slack" | "teams",
  setupNewBot: boolean,
  configTokenReady: boolean,
): WizardStep[] {
  if (agentType === "hermes") {
    if (!setupNewBot) {
      return ["template", "agent-type", "slack-choice", "slack-tokens", "details", "skills"];
    }
    const base: WizardStep[] = ["template", "agent-type", "slack-choice"];
    if (!configTokenReady) base.push("config-token");
    base.push("bot-builder", "slack-tokens", "details", "skills");
    return base;
  }
  if (platform === "teams") {
    return ["template", "agent-type", "platform-choice", "teams-credentials", "teams-bot-builder", "details", "skills"];
  }
  if (!setupNewBot) {
    return ["template", "agent-type", "platform-choice", "slack-choice", "slack-tokens", "details", "skills"];
  }
  const base: WizardStep[] = ["template", "agent-type", "platform-choice", "slack-choice"];
  if (!configTokenReady) base.push("config-token");
  base.push("bot-builder", "slack-tokens", "details", "skills");
  return base;
}

function stepOrdinal(
  step: WizardStep,
  agentType: "openclaw" | "hermes",
  platform: "slack" | "teams",
  setupNewBot: boolean,
  configTokenReady: boolean,
): string {
  const seq = getSteps(agentType, platform, setupNewBot, configTokenReady);
  return `step ${seq.indexOf(step) + 1} of ${seq.length}`;
}

function stepTitle(step: WizardStep): string {
  switch (step) {
    case "template": return "What kind of teammate do you need?";
    case "agent-type": return "Choose your agent runtime";
    case "platform-choice": return "Choose your platform";
    case "slack-choice": return "Set up your Slack app";
    case "config-token": return "Set up Slack app creation";
    case "bot-builder": return "Build your Slack bot";
    case "slack-tokens": return "Connect Slack";
    case "teams-bot-builder": return "Build your Teams bot";
    case "teams-credentials": return "Connect to Azure";
    case "details": return "A few details and we'll get them set up.";
    case "skills": return "Assign skills";
  }
}

export function HireDialog({ onClose, onHired }: HireDialogProps) {
  const createAgent = useCreateAgent();
  const createSlackApp = useCreateSlackApp();
  const startAgent = useStartAgent();
  const { hasToken: hasConfigToken, isLoading: isLoadingConfigToken } = useSlackConfigToken();
  const { saveToken } = useSlackConfigTokenActions();

  const [step, setStep] = useState<WizardStep>("template");
  const [selectedTemplate, setSelectedTemplate] = useState<AgentTemplateRead | null>(null);
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const [name, setName] = useState<string>(DEFAULT_AGENT_NAME);
  const [model, setModel] = useState<string>("");
  const [platform, setPlatform] = useState<"slack" | "teams">("slack");
  const [setupNewBot, setSetupNewBot] = useState(true);
  const [botName, setBotName] = useState<string>(DEFAULT_AGENT_NAME);
  const [botDescription, setBotDescription] = useState<string>(DEFAULT_BOT_DESCRIPTION);
  const [botColor, setBotColor] = useState("#4A154B");
  const [slackAppToken, setSlackAppToken] = useState("");
  const [slackBotToken, setSlackBotToken] = useState("");
  const [showAppToken, setShowAppToken] = useState(false);
  const [showBotToken, setShowBotToken] = useState(false);
  const [tokenError, setTokenError] = useState<string | null>(null);
  const [agentType, setAgentType] = useState<"openclaw" | "hermes">("hermes");
  const [slackGroupPolicy, setSlackGroupPolicy] = useState<"open" | "allowlist">("allowlist");
  const [slackDmPolicy, setSlackDmPolicy] = useState<"off" | "open" | "allowlist">("off");
  const [teamsAppId, setTeamsAppId] = useState("");
  const [teamsAppPassword, setTeamsAppPassword] = useState("");
  const [showTeamsAppPassword, setShowTeamsAppPassword] = useState(false);
  const [teamsTenantId, setTeamsTenantId] = useState("");
  const [teamsTokenError, setTeamsTokenError] = useState<string | null>(null);
  const [configTokenInput, setConfigTokenInput] = useState("");
  const [configRefreshInput, setConfigRefreshInput] = useState("");
  const [showConfigToken, setShowConfigToken] = useState(false);
  const [showConfigRefresh, setShowConfigRefresh] = useState(false);
  const [configTokenError, setConfigTokenError] = useState<string | null>(null);
  const [configTokenSaved, setConfigTokenSaved] = useState(false);
  const configTokenReady = configTokenSaved || (!isLoadingConfigToken && hasConfigToken);
  const [slackAppId, setSlackAppId] = useState<string | null>(null);
  const [botTokenUrl, setBotTokenUrl] = useState<string | null>(null);
  const [appTokenUrl, setAppTokenUrl] = useState<string | null>(null);
  const [createAppError, setCreateAppError] = useState<string | null>(null);
  const [selectedSkillIds, setSelectedSkillIds] = useState<string[]>([]);
  const [skillCredentials, setSkillCredentials] = useState<IntegrationDraft[]>([]);
  const [provisioning, setProvisioning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [provisionError, setProvisionError] = useState<string | null>(null);
  const [createdAgent, setCreatedAgent] = useState<Agent | null>(null);


  const progressRef = useRef(0);
  const apiDoneRef = useRef(false);
  const errorRef = useRef(false);

  const effectiveTemplate = selectedTemplate;
  const { versions, isLoading: versionsLoading } = useTemplateVersions(
    effectiveTemplate?.templateSlug,
  );
  // The chosen version (defaults to latest = versions[0]). The full row for the
  // resolved version drives the preview + submit.
  const resolvedVersion =
    selectedVersion ?? versions[0]?.version ?? effectiveTemplate?.version ?? null;
  const versionTemplate =
    versions.find((v) => v.version === resolvedVersion) ?? effectiveTemplate;
  const roleLabel = effectiveTemplate?.templateName ?? "Agent";

  function handlePickTemplate(template: AgentTemplateRead) {
    setSelectedTemplate(template);
    setSelectedVersion(null); // reset to the new lineage's latest
  }

  function handleTeamsBotNameChange(value: string) {
    setBotName(value);
    setName(value);
  }

  function handleBack() {
    const steps = getSteps(agentType, platform, setupNewBot, configTokenReady);
    const idx = steps.indexOf(step);
    if (idx > 0) setStep(steps[idx - 1]);
  }

  function handleAgentTypeChange(v: "openclaw" | "hermes") {
    setAgentType(v);
    if (v === "hermes") setPlatform("slack");
  }

  function handleContinueFromTokens() {
    if (!slackAppToken.trim() || !slackBotToken.trim()) {
      setTokenError("Both tokens are required to continue.");
      return;
    }
    if (!slackAppToken.trim().startsWith("xapp-")) {
      setTokenError("App-level token should start with xapp-");
      return;
    }
    if (!slackBotToken.trim().startsWith("xoxb-")) {
      setTokenError("Bot token should start with xoxb-");
      return;
    }
    setStep("details");
  }

  async function handleSaveConfigToken() {
    if (!configTokenInput.trim()) return;
    setConfigTokenError(null);
    try {
      await saveToken.mutateAsync({
        accessToken: configTokenInput.trim(),
        refreshToken: configRefreshInput.trim(),
      });
      setConfigTokenSaved(true);
      setConfigTokenInput("");
      setConfigRefreshInput("");
      setStep("bot-builder");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to save token";
      setConfigTokenError(msg);
    }
  }

  async function handleContinueFromBotBuilder() {
    if (configTokenReady && setupNewBot) {
      setCreateAppError(null);
      try {
        const result = await createSlackApp.mutateAsync({
          name: botName,
          description: botDescription,
          backgroundColor: botColor,
        });
        setSlackAppId(result.appId);
        setBotTokenUrl(result.botTokenUrl);
        setAppTokenUrl(result.appTokenUrl);
        setStep("slack-tokens");
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Failed to create Slack app";
        setCreateAppError(msg);
      }
    } else {
      setStep("slack-tokens");
    }
  }

  function handleContinueFromTeamsCredentials() {
    if (!teamsAppId.trim() || !teamsAppPassword.trim() || !teamsTenantId.trim()) {
      setTeamsTokenError("App ID, App Password, and Tenant ID are all required.");
      return;
    }
    setStep("teams-bot-builder");
  }

  async function startHiring() {
    if (!effectiveTemplate) return;
    setProvisioning(true);
    setProvisionError(null);
    progressRef.current = 0;
    apiDoneRef.current = false;
    errorRef.current = false;

    try {
      // Templates are stored raw; {{ … }} placeholders render server-side
      // when the agent starts.
      const agent = await createAgent.mutateAsync({
        name, model, platform,
        agentType,
        templateSlug: effectiveTemplate.templateSlug,
        ...(resolvedVersion != null ? { templateVersion: resolvedVersion } : {}),
        skillIds: [
          ...(versionTemplate?.requiredSkills?.map((s) => s.id) ?? []),
          ...selectedSkillIds,
        ],
        secrets: skillCredentials.map((c) => ({
          provider: c.provider,
          content: c.provider === "github" ? expandGithubContent(c.content) : c.content,
        })),
        ...(platform === "slack"
          ? { slackBotToken, slackAppToken, slackGroupPolicy, slackDmPolicy }
          : { teamsAppId, teamsAppPassword, teamsTenantId }),
      });
      setCreatedAgent(agent);
      apiDoneRef.current = true;
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Something went wrong. Please try again.";
      errorRef.current = true;
      progressRef.current = 0;
      setProgress(0);
      setProvisionError(msg);
    }
  }

  useEffect(() => {
    if (!provisioning) return;
    const id = setInterval(() => {
      if (errorRef.current) return;
      const cap = apiDoneRef.current ? 100 : 88;
      progressRef.current = Math.min(progressRef.current + 8 + Math.random() * 12, cap);
      setProgress(progressRef.current);
      if (progressRef.current >= 100) {
        clearInterval(id);
        setTimeout(() => setProvisioning(false), 500);
      }
    }, 240);
    return () => clearInterval(id);
  }, [provisioning]);

  if (!provisioning && createdAgent) {
    if (platform === "teams") {
      const teamsManifest = generateTeamsManifest(teamsAppId, botName, botDescription, botColor);

      return (
        <DialogShell shadeClick={undefined}>
          <header
            className="px-6 pt-6 pb-4 flex items-start justify-between"
            style={{ borderBottom: "1px solid var(--line)" }}
          >
            <div>
              <div className="text-xs uppercase tracking-[0.08em] font-semibold mb-1" style={{ color: "var(--ink-3)" }}>
                {name} · configure Teams
              </div>
              <h2 className="text-xl font-semibold tracking-tight m-0" style={{ color: "var(--ink)" }}>
                Set up the messaging endpoint
              </h2>
            </div>
            <button className="af-btn af-btn-ghost af-btn-icon" onClick={() => onHired({ name, role: roleLabel })}>
              <XIcon />
            </button>
          </header>
          <div className="flex-1 overflow-y-auto p-6">
            <p className="text-[0.8125rem] mb-5 leading-[1.5]" style={{ color: "var(--ink-3)" }}>
              {name} is hired! Set the URL below as the <b>Messaging Endpoint</b> in your Azure Bot registration → Configuration.
            </p>
            {createdAgent.webhookUrl && (
              <div
                className="flex items-center gap-2 p-4 rounded-xl font-mono text-sm"
                style={{ background: "var(--bg-soft)", border: "1px solid var(--line)" }}
              >
                <span className="flex-1 break-all" style={{ color: "var(--ink-2)" }}>
                  {createdAgent.webhookUrl}
                </span>
                <button
                  className="af-btn af-btn-sm flex-shrink-0"
                  onClick={() => void navigator.clipboard.writeText(createdAgent.webhookUrl!)}
                >
                  Copy
                </button>
              </div>
            )}
            <div
              className="mt-5 rounded-xl p-4"
              style={{ background: "var(--bg-soft)", border: "1px solid var(--line)" }}
            >
              <div className="font-semibold text-[0.844rem] mb-1" style={{ color: "var(--ink)" }}>
                Teams app package
              </div>
              <p className="text-[0.8125rem] mb-3 leading-[1.5]" style={{ color: "var(--ink-3)" }}>
                Download the ready-to-upload package if you still need to add this bot to Teams.
              </p>
              <button
                className="af-btn af-btn-sm"
                onClick={() => { void downloadTeamsAppPackage(teamsManifest, botName); }}
              >
                Download Teams app package
              </button>
            </div>
          </div>
          <footer
            className="px-6 py-4 flex items-center justify-end flex-shrink-0"
            style={{ borderTop: "1px solid var(--line)" }}
          >
            <button
              className="af-btn af-btn-primary"
              onClick={() => onHired({ name, role: roleLabel })}
            >
              Done
            </button>
          </footer>
        </DialogShell>
      );
    }

    return (
      <DialogShell shadeClick={undefined}>
        <header
          className="px-6 pt-6 pb-4 flex items-start justify-between"
          style={{ borderBottom: "1px solid var(--line)" }}
        >
          <div>
            <div className="text-xs uppercase tracking-[0.08em] font-semibold mb-1" style={{ color: "var(--ink-3)" }}>
              {name} · configure Slack
            </div>
            <h2 className="text-xl font-semibold tracking-tight m-0" style={{ color: "var(--ink)" }}>
              Set up Slack access
            </h2>
          </div>
          <button className="af-btn af-btn-ghost af-btn-icon" onClick={() => onHired({ name, role: roleLabel })}>
            <XIcon />
          </button>
        </header>
        <div className="flex-1 overflow-y-auto p-6">
          <p className="text-[0.8125rem] mb-5 leading-[1.5]" style={{ color: "var(--ink-3)" }}>
            {name} is hired! Configure which channels and users they can access, or skip to do this later from their settings.
          </p>
          <SlackConfigPanel
            agent={createdAgent}
            onSaved={() => {
              void startAgent.mutateAsync(createdAgent.id).then(() => {
                onHired({ name, role: roleLabel });
              });
            }}
          />
        </div>
        <footer
          className="px-6 py-4 flex items-center justify-end flex-shrink-0"
          style={{ borderTop: "1px solid var(--line)" }}
        >
          <button
            className="af-btn af-btn-ghost"
            onClick={() => {
              void startAgent.mutateAsync(createdAgent.id).then(() => {
                onHired({ name, role: roleLabel });
              });
            }}
          >
            Skip for now
          </button>
        </footer>
      </DialogShell>
    );
  }

  if (provisioning) {
    return (
      <DialogShell shadeClick={undefined}>
        <div className="flex flex-col items-center text-center py-12 px-8">
          <div className="text-6xl mb-6">🤖</div>
          <h2 className="text-2xl font-semibold tracking-tight mb-2" style={{ color: "var(--ink)" }}>
            Hiring {name}…
          </h2>
          <p className="text-sm mb-8" style={{ color: "var(--ink-3)" }}>
            A few moments — provisioning, installing skills, connecting to {platform === "teams" ? "Teams" : "Slack"}.
          </p>
          <div className="w-full max-w-sm mb-8">
            <div className="w-full h-1.5 rounded-full overflow-hidden" style={{ background: "var(--bg-soft)" }}>
              <div
                className="h-full rounded-full transition-all duration-300"
                style={{ width: `${progress}%`, background: "var(--ink)" }}
              />
            </div>
          </div>
          <div className="flex flex-col gap-2.5 text-left w-full max-w-sm">
            {PROVISION_STEPS.map((s, i) => {
              const done = progress >= s.at;
              const pending = s.isPending && done && progress < 100;
              const text = s.isPending ? "Finishing up…" : s.text;
              return (
                <div key={i} className="flex items-center gap-3 text-[0.844rem]">
                  <div className="w-5 h-5 flex-shrink-0 grid place-items-center">
                    {pending ? (
                      <div
                        className="w-4 h-4 rounded-full border-2 border-t-transparent animate-spin"
                        style={{ borderColor: "var(--ink-3)", borderTopColor: "transparent" }}
                      />
                    ) : done ? (
                      <CheckIcon style={{ color: "var(--ok)" }} />
                    ) : (
                      <div className="w-1.5 h-1.5 rounded-full" style={{ background: "var(--ink-5)" }} />
                    )}
                  </div>
                  <span style={{ color: done ? "var(--ink)" : "var(--ink-4)" }}>{text}</span>
                </div>
              );
            })}
          </div>

          {provisionError && (
            <div
              className="mt-6 w-full max-w-sm rounded-xl px-4 py-3 text-sm text-left"
              style={{ background: "var(--err-soft, #fef2f2)", color: "var(--err)" }}
            >
              <div className="font-semibold mb-1">Something went wrong</div>
              <div className="text-[0.8125rem]">{provisionError}</div>
              <button
                className="af-btn af-btn-sm mt-3"
                onClick={() => { setProvisioning(false); setProvisionError(null); }}
              >
                Go back
              </button>
            </div>
          )}
        </div>
      </DialogShell>
    );
  }

  return (
    <DialogShell shadeClick={onClose}>
      <header
        className="px-6 pt-6 pb-4 flex items-start justify-between"
        style={{ borderBottom: "1px solid var(--line)" }}
      >
        <div>
          <div className="text-xs uppercase tracking-[0.08em] font-semibold mb-1" style={{ color: "var(--ink-3)" }}>
            Hire · {stepOrdinal(step, agentType, platform, setupNewBot, configTokenReady)}
          </div>
          <h2 className="text-xl font-semibold tracking-tight m-0" style={{ color: "var(--ink)" }}>
            {stepTitle(step)}
          </h2>
        </div>
        <button className="af-btn af-btn-ghost af-btn-icon" onClick={onClose}>
          <XIcon />
        </button>
      </header>

      <div className="flex-1 overflow-y-auto p-6">
        {step === "template" && (
          <TemplateStep
            selectedSlug={effectiveTemplate?.templateSlug ?? null}
            onPick={handlePickTemplate}
            versions={versions}
            versionsLoading={versionsLoading}
            selectedVersion={resolvedVersion}
            onVersionChange={setSelectedVersion}
          />
        )}
        {step === "agent-type" && <AgentTypeStep agentType={agentType} onChange={handleAgentTypeChange} />}
        {step === "platform-choice" && <PlatformChoiceStep platform={platform} onChange={setPlatform} />}
        {step === "slack-choice" && <SlackChoiceStep setupNewBot={setupNewBot} onChange={setSetupNewBot} />}
        {step === "config-token" && (
          <ConfigTokenStep
            tokenInput={configTokenInput}
            onTokenInputChange={(v) => { setConfigTokenInput(v); setConfigTokenError(null); }}
            showToken={showConfigToken}
            onToggleToken={() => setShowConfigToken((v) => !v)}
            refreshInput={configRefreshInput}
            onRefreshInputChange={(v) => { setConfigRefreshInput(v); setConfigTokenError(null); }}
            showRefresh={showConfigRefresh}
            onToggleRefresh={() => setShowConfigRefresh((v) => !v)}
            isSaving={saveToken.isPending}
            error={configTokenError}
          />
        )}
        {step === "bot-builder" && (
          <>
            <BotBuilderStep
              botName={botName} onBotNameChange={(v) => { setBotName(v); setName(v); }}
              botDescription={botDescription} onBotDescriptionChange={setBotDescription}
              botColor={botColor} onBotColorChange={setBotColor}
            />
            {createAppError && (
              <div className="mt-3 text-[0.8125rem]" style={{ color: "var(--err)" }}>
                {createAppError}
              </div>
            )}
          </>
        )}
        {step === "slack-tokens" && (
          <SlackTokensStep
            slackAppToken={slackAppToken}
            onAppTokenChange={(v) => { setSlackAppToken(v); setTokenError(null); }}
            slackBotToken={slackBotToken}
            onBotTokenChange={(v) => { setSlackBotToken(v); setTokenError(null); }}
            showAppToken={showAppToken} onToggleAppToken={() => setShowAppToken((v) => !v)}
            showBotToken={showBotToken} onToggleBotToken={() => setShowBotToken((v) => !v)}
            error={tokenError}
            appId={slackAppId}
            botTokenUrl={botTokenUrl}
            appTokenUrl={appTokenUrl}
          />
        )}
        {step === "teams-bot-builder" && (
          <TeamsBotBuilderStep
            teamsAppId={teamsAppId} onTeamsAppIdChange={setTeamsAppId}
            botName={botName} onBotNameChange={handleTeamsBotNameChange}
            botDescription={botDescription} onBotDescriptionChange={setBotDescription}
            botColor={botColor} onBotColorChange={setBotColor}
          />
        )}
        {step === "teams-credentials" && (
          <TeamsCredentialsStep
            teamsAppId={teamsAppId}
            onAppIdChange={(v) => { setTeamsAppId(v); setTeamsTokenError(null); }}
            teamsAppPassword={teamsAppPassword}
            onAppPasswordChange={(v) => { setTeamsAppPassword(v); setTeamsTokenError(null); }}
            showAppPassword={showTeamsAppPassword}
            onToggleAppPassword={() => setShowTeamsAppPassword((v) => !v)}
            teamsTenantId={teamsTenantId}
            onTenantIdChange={(v) => { setTeamsTenantId(v); setTeamsTokenError(null); }}
            error={teamsTokenError}
          />
        )}
        {step === "details" && versionTemplate && (
          <DetailsStep
            template={versionTemplate}
            platform={platform}
            name={name} onNameChange={setName}
            model={model} onModelChange={setModel}
            slackGroupPolicy={slackGroupPolicy} onSlackGroupPolicyChange={(v) => setSlackGroupPolicy(v as "open" | "allowlist")}
            slackDmPolicy={slackDmPolicy} onSlackDmPolicyChange={(v) => setSlackDmPolicy(v as "off" | "open" | "allowlist")}
            onChangeTemplate={() => setStep("template")}
          />
        )}
        {step === "skills" && (
          <SkillsStep
            selectedSkillIds={selectedSkillIds}
            skillCredentials={skillCredentials}
            onSkillIdsChange={setSelectedSkillIds}
            onSkillCredentialsChange={setSkillCredentials}
            templateRequiredSkills={versionTemplate?.requiredSkills ?? []}
          />
        )}
      </div>

      <footer
        className="px-6 py-4 flex items-center justify-between flex-shrink-0"
        style={{ borderTop: "1px solid var(--line)" }}
      >
        {step === "template" ? (
          <button className="af-btn af-btn-ghost" onClick={onClose}>Cancel</button>
        ) : (
          <button className="af-btn" onClick={handleBack}>Back</button>
        )}

        {step === "template" && (
          <button
            className="af-btn af-btn-primary af-btn-lg"
            disabled={!effectiveTemplate}
            onClick={() => setStep("agent-type")}
          >
            Continue
          </button>
        )}
        {step === "agent-type" && (
          <button
            className="af-btn af-btn-primary af-btn-lg"
            onClick={() => setStep(agentType === "hermes" ? "slack-choice" : "platform-choice")}
          >
            Continue
          </button>
        )}
        {step === "platform-choice" && (
          <button
            className="af-btn af-btn-primary af-btn-lg"
            onClick={() => setStep(platform === "teams" ? "teams-credentials" : "slack-choice")}
          >
            Continue
          </button>
        )}
        {step === "slack-choice" && (
          <button
            className="af-btn af-btn-primary af-btn-lg"
            onClick={() => {
              if (!setupNewBot) { setStep("slack-tokens"); return; }
              setStep(configTokenReady ? "bot-builder" : "config-token");
            }}
          >
            Continue
          </button>
        )}
        {step === "config-token" && (
          <button
            className="af-btn af-btn-primary af-btn-lg"
            disabled={!configTokenInput.trim() || !configRefreshInput.trim() || saveToken.isPending}
            onClick={() => { void handleSaveConfigToken(); }}
          >
            {saveToken.isPending ? "Validating..." : "Save & continue"}
          </button>
        )}
        {step === "bot-builder" && (
          <button
            className="af-btn af-btn-primary af-btn-lg"
            disabled={!botName.trim() || createSlackApp.isPending}
            onClick={() => { void handleContinueFromBotBuilder(); }}
          >
            {createSlackApp.isPending ? "Creating app..." : "Continue"}
          </button>
        )}
        {step === "slack-tokens" && (
          <button className="af-btn af-btn-primary af-btn-lg" onClick={handleContinueFromTokens}>
            Continue
          </button>
        )}
        {step === "teams-bot-builder" && (
          <button className="af-btn af-btn-primary af-btn-lg" onClick={() => setStep("details")}>
            Continue
          </button>
        )}
        {step === "teams-credentials" && (
          <button className="af-btn af-btn-primary af-btn-lg" onClick={handleContinueFromTeamsCredentials}>
            Continue
          </button>
        )}
        {step === "details" && (
          <button
            className="af-btn af-btn-primary af-btn-lg"
            disabled={!name.trim()}
            onClick={() => {
              // Pre-populate credential drafts for template required skills.
              const requiredProviders = [
                ...new Set(
                  (versionTemplate?.requiredSkills ?? []).flatMap((s) => s.requiredProviders),
                ),
              ];
              setSkillCredentials((prev) => {
                const existing = new Set(prev.map((c) => c.provider));
                const toAdd = requiredProviders.filter((p) => !existing.has(p));
                if (toAdd.length === 0) return prev;
                return [...prev, ...toAdd.map((p) => ({ provider: p, content: {} }))];
              });
              setStep("skills");
            }}
          >
            Continue
          </button>
        )}
        {step === "skills" && (
          <button
            className="af-btn af-btn-primary af-btn-lg"
            disabled={!name.trim() || hasIncompleteIntegration(skillCredentials)}
            onClick={() => { void startHiring(); }}
          >
            Hire {name}
          </button>
        )}
      </footer>
    </DialogShell>
  );
}
