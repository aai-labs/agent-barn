"use client";

import { useState, useEffect, useRef } from "react";
import { XIcon, CheckIcon } from "@/components/icons";
import { useCreateAgent } from "../hooks/use-create-agent";
import { DialogShell } from "./hire-dialog-primitives";
import {
  ROLES, MODELS, RoleId, WizardStep, pickDefaults,
  RoleStep, SlackChoiceStep, BotBuilderStep, SlackTokensStep, DetailsStep,
} from "./hire-dialog-steps";
import { SlackConfigPanel } from "./slack-config-panel";
import type { Agent } from "../schemas";

interface HireDialogProps {
  onClose: () => void;
  onHired: (info: { name: string; role: string }) => void;
}

const PROVISION_STEPS = [
  { at: 14, text: "Resolved template" },
  { at: 32, text: "Created workspace and config" },
  { at: 50, text: "Issued provider keys (vaulted)" },
  { at: 68, text: "Locked network egress" },
  { at: 84, text: "Started agent" },
  { at: 96, text: "", isPending: true },
];

function stepOrdinal(step: WizardStep, setupNewBot: boolean): string {
  const seq: WizardStep[] = setupNewBot
    ? ["role", "slack-choice", "bot-builder", "slack-tokens", "details"]
    : ["role", "slack-choice", "slack-tokens", "details"];
  return `step ${seq.indexOf(step) + 1} of ${seq.length}`;
}

function stepTitle(step: WizardStep): string {
  switch (step) {
    case "role": return "What kind of teammate do you need?";
    case "slack-choice": return "Set up your Slack app";
    case "bot-builder": return "Build your Slack bot";
    case "slack-tokens": return "Connect Slack";
    case "details": return "A few details and we'll get them set up.";
  }
}

export function HireDialog({ onClose, onHired }: HireDialogProps) {
  const createAgent = useCreateAgent();

  const [step, setStep] = useState<WizardStep>("role");
  const [pick, setPick] = useState<RoleId>("default");
  const defaults = pickDefaults("default");
  const [name, setName] = useState<string>(defaults.name);
  const [model, setModel] = useState<string>(MODELS[0].value);
  const [setupNewBot, setSetupNewBot] = useState(false);
  const [botName, setBotName] = useState<string>(defaults.botName);
  const [botDescription, setBotDescription] = useState<string>(defaults.botDescription);
  const [botColor, setBotColor] = useState("#4A154B");
  const [slackAppToken, setSlackAppToken] = useState("");
  const [slackBotToken, setSlackBotToken] = useState("");
  const [showAppToken, setShowAppToken] = useState(false);
  const [showBotToken, setShowBotToken] = useState(false);
  const [tokenError, setTokenError] = useState<string | null>(null);
  const [slackGroupPolicy, setSlackGroupPolicy] = useState<"open" | "allowlist">("allowlist");
  const [slackDmPolicy, setSlackDmPolicy] = useState<"off" | "open" | "allowlist" | "pairing">("off");
  const [soulMd, setSoulMd] = useState(defaults.soulMd);
  const [identityMd, setIdentityMd] = useState(defaults.identityMd);
  const [userMd, setUserMd] = useState(defaults.userMd);
  const [toolsMd, setToolsMd] = useState(defaults.toolsMd);
  const [provisioning, setProvisioning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [provisionError, setProvisionError] = useState<string | null>(null);
  const [createdAgent, setCreatedAgent] = useState<Agent | null>(null);

  const progressRef = useRef(0);
  const apiDoneRef = useRef(false);

  const selected = ROLES.find((r) => r.id === pick)!;

  function handlePickRole(roleId: RoleId) {
    const d = pickDefaults(roleId);
    setPick(roleId);
    setName(d.name);
    setBotName(d.botName);
    setBotDescription(d.botDescription);
    setSoulMd(d.soulMd);
    setIdentityMd(d.identityMd);
    setUserMd(d.userMd);
    setToolsMd(d.toolsMd);
  }

  function handleBack() {
    if (step === "details") setStep("slack-tokens");
    else if (step === "slack-tokens") setStep(setupNewBot ? "bot-builder" : "slack-choice");
    else if (step === "bot-builder") setStep("slack-choice");
    else if (step === "slack-choice") setStep("role");
  }

  function handleContinueFromTokens() {
    if (!slackAppToken.trim() || !slackBotToken.trim()) {
      setTokenError("Both tokens are required to continue.");
      return;
    }
    setStep("details");
  }

  async function startHiring() {
    setProvisioning(true);
    setProvisionError(null);
    progressRef.current = 0;
    apiDoneRef.current = false;

    try {
      const agent = await createAgent.mutateAsync({
        name, model, slackBotToken, slackAppToken,
        soulMd, identityMd, userMd, toolsMd,
        slackGroupPolicy, slackDmPolicy,
      });
      setCreatedAgent(agent);
      apiDoneRef.current = true;
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Something went wrong. Please try again.";
      setProvisionError(msg);
    }
  }

  useEffect(() => {
    if (!provisioning) return;
    const id = setInterval(() => {
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
          <button className="af-btn af-btn-ghost af-btn-icon" onClick={() => onHired({ name, role: selected.title })}>
            <XIcon />
          </button>
        </header>
        <div className="flex-1 overflow-y-auto p-6">
          <p className="text-[0.8125rem] mb-5 leading-[1.5]" style={{ color: "var(--ink-3)" }}>
            {name} is hired! Configure which channels and users they can access, or skip to do this later from their settings.
          </p>
          <SlackConfigPanel
            agent={createdAgent}
            onSaved={() => onHired({ name, role: selected.title })}
          />
        </div>
        <footer
          className="px-6 py-4 flex items-center justify-end flex-shrink-0"
          style={{ borderTop: "1px solid var(--line)" }}
        >
          <button
            className="af-btn af-btn-ghost"
            onClick={() => onHired({ name, role: selected.title })}
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
          <div className="text-6xl mb-6">{selected.emoji}</div>
          <h2 className="text-2xl font-semibold tracking-tight mb-2" style={{ color: "var(--ink)" }}>
            Hiring {name}…
          </h2>
          <p className="text-sm mb-8" style={{ color: "var(--ink-3)" }}>
            A few moments — provisioning, installing skills, connecting to Slack.
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
              const text = s.isPending ? `${name} said hello in Slack` : s.text;
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
            Hire · {stepOrdinal(step, setupNewBot)}
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
        {step === "role" && <RoleStep pick={pick} onPick={handlePickRole} />}
        {step === "slack-choice" && <SlackChoiceStep setupNewBot={setupNewBot} onChange={setSetupNewBot} />}
        {step === "bot-builder" && (
          <BotBuilderStep
            botName={botName} onBotNameChange={setBotName}
            botDescription={botDescription} onBotDescriptionChange={setBotDescription}
            botColor={botColor} onBotColorChange={setBotColor}
          />
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
          />
        )}
        {step === "details" && (
          <DetailsStep
            selected={selected}
            name={name} onNameChange={setName}
            model={model} onModelChange={setModel}
            slackGroupPolicy={slackGroupPolicy} onSlackGroupPolicyChange={(v) => setSlackGroupPolicy(v as "open" | "allowlist")}
            slackDmPolicy={slackDmPolicy} onSlackDmPolicyChange={(v) => setSlackDmPolicy(v as "off" | "open" | "allowlist" | "pairing")}
            soulMd={soulMd} onSoulMdChange={setSoulMd}
            identityMd={identityMd} onIdentityMdChange={setIdentityMd}
            userMd={userMd} onUserMdChange={setUserMd}
            toolsMd={toolsMd} onToolsMdChange={setToolsMd}
            onChangeRole={() => setStep("role")}
          />
        )}
      </div>

      <footer
        className="px-6 py-4 flex items-center justify-between flex-shrink-0"
        style={{ borderTop: "1px solid var(--line)" }}
      >
        {step === "role" ? (
          <button className="af-btn af-btn-ghost" onClick={onClose}>Cancel</button>
        ) : (
          <button className="af-btn" onClick={handleBack}>Back</button>
        )}

        {step === "role" && (
          <button className="af-btn af-btn-primary af-btn-lg" onClick={() => setStep("slack-choice")}>
            Continue
          </button>
        )}
        {step === "slack-choice" && (
          <button
            className="af-btn af-btn-primary af-btn-lg"
            onClick={() => setStep(setupNewBot ? "bot-builder" : "slack-tokens")}
          >
            Continue
          </button>
        )}
        {step === "bot-builder" && (
          <button className="af-btn af-btn-primary af-btn-lg" onClick={() => setStep("slack-tokens")}>
            Continue
          </button>
        )}
        {step === "slack-tokens" && (
          <button className="af-btn af-btn-primary af-btn-lg" onClick={handleContinueFromTokens}>
            Continue
          </button>
        )}
        {step === "details" && (
          <button
            className="af-btn af-btn-primary af-btn-lg"
            disabled={!name.trim()}
            onClick={() => { void startHiring(); }}
          >
            Hire {name}
          </button>
        )}
      </footer>
    </DialogShell>
  );
}
