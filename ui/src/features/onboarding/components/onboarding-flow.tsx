"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { useCurrentUser } from "@/auth/providers/user-context-provider";
import { AppErrorState } from "@/components/app-error-state";
import type { HiredAgent } from "@/features/agents/hooks/use-hire-agent-form";
import { useOrganization } from "@/features/organizations/hooks/use-organization";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";
import { useOrgStore } from "@/features/organizations/stores/org-store";
import { getErrorDisplay } from "@/shared/api/error/get-error-display";

import { useOnboarding, useOnboardingActions } from "../hooks/use-onboarding";
import type { Onboarding } from "../schemas";
import { AccountOpeningScreen } from "./account-opening-screen";
import { ChooseStep, ContinueButton } from "./choose-step";
import { DoneStep } from "./done-step";
import { OnboardingShell, StepAlert, type OnboardingPath } from "./onboarding-shell";
import { SetupStep } from "./setup-step";
import { TelegramStep } from "./telegram-step";

export function OnboardingFlow() {
  const router = useRouter();
  const { user } = useCurrentUser();
  const { selectedOrganization } = useOrganizationContext();
  const setOrganizationId = useOrgStore((state) => state.setOrganizationId);
  const { onboarding: currentOnboarding, isLoadingOnboarding, onboardingError, reloadOnboarding } = useOnboarding();
  const { setUpAgent, complete } = useOnboardingActions();
  const [path, setPath] = useState<OnboardingPath>("quick");
  const [stage, setStage] = useState<"choose" | "setup" | "finish" | "done">("choose");
  const [hired, setHired] = useState<HiredAgent | null>(null);
  const [telegramUsername, setTelegramUsername] = useState<string | null>(null);
  const [skipping, setSkipping] = useState(false);
  const [returnToDashboard, setReturnToDashboard] = useState(false);
  // Completion retires the API's setup details. Keep this visit's summary and
  // navigation targets while the completed status refreshes in the query cache.
  const [finishedSetup, setFinishedSetup] = useState<Onboarding | null>(null);
  const onboarding = finishedSetup ?? currentOnboarding;
  const trialOrganizationId = onboarding?.organizationId ?? null;
  const { organization } = useOrganization(trialOrganizationId ?? "");
  const organizationReady = selectedOrganization?.id === trialOrganizationId;

  useEffect(() => {
    if (onboarding && !onboarding.required && stage === "choose") router.replace("/dashboard");
  }, [onboarding, stage, router]);

  useEffect(() => {
    if (trialOrganizationId && !organizationReady) setOrganizationId(user.id, trialOrganizationId);
  }, [trialOrganizationId, organizationReady, setOrganizationId, user.id]);

  if (isLoadingOnboarding) return <AccountOpeningScreen />;
  if (onboardingError && !finishedSetup) {
    return (
      <AppErrorState
        error={onboardingError}
        title="We couldn't load your setup"
        onRetry={() => void reloadOnboarding()}
        className="min-h-svh"
      />
    );
  }
  if (!onboarding || (!onboarding.required && stage === "choose") || !organizationReady) {
    return <AccountOpeningScreen opening />;
  }

  const home = trialOrganizationId ? `/dashboard/${trialOrganizationId}` : "/dashboard";
  const agentId = hired?.id ?? onboarding.agentId;
  const agentName = hired?.name ?? onboarding.agentName ?? "your agent";
  const shell = { email: user.email, creditUsd: onboarding.creditUsd ?? null };

  function finish(username: string | null = null, dashboard = returnToDashboard) {
    setFinishedSetup(onboarding ?? null);
    setTelegramUsername(username);
    setReturnToDashboard(dashboard);
    setStage("finish");
    complete.mutate(undefined, {
      onSuccess: () => dashboard ? router.push(home) : setStage("done"),
    });
  }

  function choosePath() {
    setStage("setup");
    if (onboarding?.agentId || path === "quick") {
      setPath("quick");
      setUpAgent.mutate();
    }
  }

  if (stage === "done") {
    return (
      <DoneStep
        {...shell}
        path={path}
        agentName={agentName}
        telegramUsername={telegramUsername}
        botUsername={onboarding.telegramBotUsername ?? null}
        onDashboard={() => router.push(home)}
        chatHref={`${home}/agents/${agentId}?tab=chat`}
        channelsHref={`${home}/agents/${agentId}/configuration?section=channels&connect=true`}
      />
    );
  }

  // Retry only completion: creating or starting the Agent again could consume a
  // trial slot or fail because it is already running.
  if (stage === "finish") {
    return (
      <OnboardingShell
        {...shell}
        path={path}
        step={3}
        title="Finishing your setup"
        footerEnd={
          <button
            type="button"
            className="af-btn af-btn-primary af-btn-lg"
            disabled={complete.isPending}
            onClick={() => finish(telegramUsername)}
          >
            {complete.isPending ? "Saving…" : "Try again"}
          </button>
        }
      >
        {complete.isError && <StepAlert>We couldn&apos;t save your progress. Try again.</StepAlert>}
      </OnboardingShell>
    );
  }

  if (stage === "choose") {
    return (
      <OnboardingShell
        {...shell}
        path={path}
        step={1}
        title="How do you want to start?"
        subtitle="Start with an assistant that's ready to go, or make one your own."
        footerStart={
          <button type="button" className="af-btn af-btn-ghost" onClick={() => finish(null, true)}>
            I&apos;ll do this later
          </button>
        }
        footerEnd={onboarding.agentId && !onboarding.connectionId ? (
          <button
            type="button"
            className="af-btn af-btn-primary af-btn-lg"
            onClick={() => { setPath("own"); finish(null, true); }}
          >
            Go to dashboard
          </button>
        ) : <ContinueButton onClick={choosePath} />}
      >
        {onboarding.agentId ? (
          <p>You already have {agentName}. Continue with this agent to keep your trial slot.</p>
        ) : (
          <ChooseStep path={path} onPathChange={setPath} agentLimit={organization?.trialAgentLimit ?? null} />
        )}
      </OnboardingShell>
    );
  }

  if (path === "own") {
    return (
      <SetupStep
        {...shell}
        onBack={() => setStage("choose")}
        onLater={() => finish(null, true)}
        onHired={(agent) => { setHired(agent); finish(); }}
      />
    );
  }

  const ready = onboarding.agentStatus === "RUNNING" && onboarding.agentId && onboarding.connectionId;
  const setUpError = setUpAgent.isError
    ? `We couldn't set up your agent: ${getErrorDisplay(setUpAgent.error).description}`
    : onboarding.agentStatus === "ERROR" && !setUpAgent.isPending
      ? "We couldn't start your agent. Try again in a moment."
      : null;

  return (
    <TelegramStep
      {...shell}
      agentName={agentName}
      botUsername={onboarding.telegramBotUsername ?? null}
      agent={ready ? { id: onboarding.agentId!, connectionId: onboarding.connectionId! } : null}
      setUpError={setUpError}
      onRetrySetUp={() => setUpAgent.mutate()}
      onContinue={(username) => finish(username)}
      isContinuing={complete.isPending}
      onSkip={() => {
        setSkipping(true);
        complete.mutate(undefined, {
          onSuccess: () => router.push(`${home}/agents/${agentId}?tab=chat`),
          onError: () => setSkipping(false),
        });
      }}
      isSkipping={skipping}
      finishError={complete.isError}
    />
  );
}
