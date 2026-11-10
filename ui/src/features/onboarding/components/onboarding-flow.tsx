"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";

import { useCurrentUser } from "@/auth/providers/user-context-provider";
import { currentUserContextKey } from "@/auth/utils";
import { AppErrorState } from "@/components/app-error-state";
import type { HiredAgent } from "@/features/agents/hooks/use-hire-agent-form";
import { useOrganization } from "@/features/organizations/hooks/use-organization";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";
import { useOrgStore } from "@/features/organizations/stores/org-store";
import { organizationsKey } from "@/features/organizations/utils";
import { PAYMENT_WAIT_MS, useOrganizationBilling } from "@/features/billing/hooks/use-organization-billing";
import { useSubscriptionActions } from "@/features/billing/hooks/use-subscription-actions";
import { useOfferedTiers } from "@/features/tiers/hooks/use-offered-tiers";
import { getErrorDisplay } from "@/shared/api/error/get-error-display";

import { useOnboarding, useOnboardingActions } from "../hooks/use-onboarding";
import type { Onboarding } from "../schemas";
import { AccountOpeningScreen } from "./account-opening-screen";
import { ChooseStep, ContinueButton } from "./choose-step";
import { DoneStep } from "./done-step";
import { GmailStep } from "./gmail-step";
import { OnboardingShell, StepAlert, type OnboardingPath } from "./onboarding-shell";
import { SetupStep } from "./setup-step";
import { TelegramStep } from "./telegram-step";
import { TierStep } from "./tier-step";

export function OnboardingFlow() {
  const router = useRouter();
  const { user } = useCurrentUser();
  const { selectedOrganization } = useOrganizationContext();
  const setOrganizationId = useOrgStore((state) => state.setOrganizationId);
  const { onboarding: currentOnboarding, isLoadingOnboarding, onboardingError, reloadOnboarding } = useOnboarding();
  const { setUpAgent, complete } = useOnboardingActions();
  const [path, setPath] = useState<OnboardingPath>("quick");
  const [stage, setStage] = useState<"choose" | "setup" | "gmail" | "finish" | "done">("choose");
  const [hired, setHired] = useState<HiredAgent | null>(null);
  const [telegramUsername, setTelegramUsername] = useState<string | null>(null);
  const [skipping, setSkipping] = useState(false);
  // Where finishing goes: the dashboard, Web Chat, or the ready screen when null.
  const [returnTo, setReturnTo] = useState<string | null>(null);
  // Completion retires the API's setup details. Keep this visit's summary and
  // navigation targets while the completed status refreshes in the query cache.
  const [finishedSetup, setFinishedSetup] = useState<Onboarding | null>(null);
  const onboarding = finishedSetup ?? currentOnboarding;
  const trialOrganizationId = onboarding?.organizationId ?? null;
  const { organization } = useOrganization(trialOrganizationId ?? "");
  const organizationReady = selectedOrganization?.id === trialOrganizationId;
  // The tier step comes first while there is a tier to choose, and once only.
  const searchParams = useSearchParams();
  const requestedTier = searchParams?.get("tier") ?? null;
  // Back from a payment provider's page: wait for its confirmation before going on.
  const [subscriptionReturn] = useState(() => searchParams?.get("subscription") ?? null);
  const [confirmSlow, setConfirmSlow] = useState(false);
  const { billing } = useOrganizationBilling(trialOrganizationId ?? undefined, {
    awaitingPayment: subscriptionReturn === "started",
  });
  const confirming = subscriptionReturn === "started" && !billing?.subscription;
  const queryClient = useQueryClient();
  const { tiers } = useOfferedTiers();
  const { subscribe } = useSubscriptionActions(trialOrganizationId ?? "", { returnTo: "onboarding" });
  const [tierChosen, setTierChosen] = useState(false);
  const allows = (feature: string) => !organization?.entitlements || organization.entitlements.features.includes(feature);
  // The shared Telegram bot is the free trial's quick start; a paid organization chats on the web.
  const paid = organization ? !organization.isTrial : false;

  useEffect(() => {
    if (searchParams?.get("subscription")) router.replace("/onboarding");
  }, [searchParams, router]);

  useEffect(() => {
    if (subscriptionReturn !== "started") return;
    const timer = setTimeout(() => setConfirmSlow(true), PAYMENT_WAIT_MS);
    return () => clearTimeout(timer);
  }, [subscriptionReturn]);

  useEffect(() => {
    if (subscriptionReturn !== "started" || !billing?.subscription || !trialOrganizationId) return;
    // The tier, its entitlements and the trial changed with the subscription.
    void queryClient.invalidateQueries({ queryKey: organizationsKey.detail(trialOrganizationId) });
    void queryClient.invalidateQueries({ queryKey: currentUserContextKey.all });
  }, [subscriptionReturn, billing?.subscription, trialOrganizationId, queryClient]);

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
  const chatHref = `${home}/agents/${agentId}?tab=chat`;
  const shell = {
    email: user.email,
    creditUsd: onboarding.creditUsd ?? null,
    sharedBot: !paid,
    planName: paid && organization?.tier ? organization.tier.name : "Free trial",
  };

  function finish(username: string | null = null, to = returnTo) {
    setFinishedSetup(onboarding ?? null);
    setTelegramUsername(username);
    setReturnTo(to);
    setStage("finish");
    complete.mutate(undefined, {
      onSuccess: () => to ? router.push(to) : setStage("done"),
    });
  }

  function choosePath() {
    setStage("setup");
    if (onboarding?.agentId || path === "quick") {
      setPath("quick");
      setUpAgent.mutate(undefined, {
        // Without the shared bot, the next step is Gmail, then Web Chat.
        onSuccess: (set) => {
          if (!paid || !set.agentId) return;
          const chat = `${home}/agents/${set.agentId}?tab=chat`;
          setReturnTo(chat);
          if (allows("integrations")) setStage("gmail");
          else finish(null, chat);
        },
      });
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
        chatHref={chatHref}
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
        step={4}
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

  if (stage === "choose" && confirming) {
    return (
      <OnboardingShell
        {...shell}
        path={path}
        step={1}
        choosingTier
        title={confirmSlow ? "Your payment is still being confirmed" : "Confirming your payment"}
        subtitle={
          confirmSlow
            ? "Your subscription starts as soon as it's confirmed. You can keep waiting here, or set up later from your dashboard."
            : "Payment received. Your subscription starts in a moment."
        }
        footerStart={
          <button type="button" className="af-btn af-btn-ghost" onClick={() => finish(null, home)}>
            I&apos;ll do this later
          </button>
        }
      >
        <p role="status" className="m-0 text-sm" style={{ color: "var(--ink-3)" }}>
          Waiting for the payment provider…
        </p>
      </OnboardingShell>
    );
  }

  const onNone = organization?.tier?.activation === "none";
  if (
    stage === "choose" &&
    !tierChosen &&
    !onboarding.agentId &&
    !billing?.subscription &&
    (billing?.subscriptionsAvailable || onNone)
  ) {
    return (
      <OnboardingShell
        {...shell}
        path={path}
        step={1}
        choosingTier
        title="Choose your tier"
        subtitle={onNone ? "Free has already been used with this address. Choose a tier to get started." : "Start free, or pick a tier with more agents and the full platform."}
        footerStart={
          <button type="button" className="af-btn af-btn-ghost" onClick={() => finish(null, home)}>
            I&apos;ll do this later
          </button>
        }
      >
        {subscribe.isError && <StepAlert>{getErrorDisplay(subscribe.error).description}</StepAlert>}
        {subscriptionReturn === "cancelled" && <StepAlert>Checkout cancelled. Nothing was charged.</StepAlert>}
        <TierStep
          tiers={tiers}
          currentKey={organization?.tier?.key ?? null}
          requestedKey={requestedTier}
          canSubscribe={Boolean(billing?.subscriptionsAvailable)}
          subscribingKey={subscribe.isPending ? (subscribe.variables ?? null) : null}
          onContinue={() => setTierChosen(true)}
          onSubscribe={(tier) => subscribe.mutate(tier.key, { onSuccess: () => setTierChosen(true) })}
        />
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
          <button type="button" className="af-btn af-btn-ghost" onClick={() => finish(null, home)}>
            I&apos;ll do this later
          </button>
        }
        footerEnd={onboarding.agentId && !onboarding.connectionId ? (
          <button
            type="button"
            className="af-btn af-btn-primary af-btn-lg"
            onClick={() => { setPath("own"); finish(null, home); }}
          >
            Go to dashboard
          </button>
        ) : <ContinueButton onClick={choosePath} />}
      >
        {onboarding.agentId ? (
          <p>You already have {agentName}. Continue with this agent to keep your trial slot.</p>
        ) : (
          <ChooseStep path={path} onPathChange={setPath} agentLimit={organization?.trialAgentLimit ?? null} allowsCustom={!organization?.entitlements || organization.entitlements.features.includes("custom_agents")} sharedBot={!paid} />
        )}
      </OnboardingShell>
    );
  }

  // Connecting Gmail is optional, so it comes once the Agent exists and before the ready screen.
  if (stage === "gmail" && agentId) {
    return (
      <GmailStep
        {...shell}
        path={path}
        agentId={agentId}
        onDone={() => finish(telegramUsername)}
        onLater={() => finish(null, returnTo ?? home)}
      />
    );
  }

  if (path === "own") {
    return (
      <SetupStep
        {...shell}
        onBack={() => setStage("choose")}
        onLater={() => finish(null, home)}
        onHired={(agent) => {
          setHired(agent);
          // Connecting Gmail adds an integration, which the tier may leave out.
          if (allows("integrations")) setStage("gmail");
          else finish(null);
        }}
      />
    );
  }

  const ready = onboarding.agentStatus === "RUNNING" && onboarding.agentId && onboarding.connectionId;
  const setUpError = setUpAgent.isError
    ? `We couldn't set up your agent: ${getErrorDisplay(setUpAgent.error).description}`
    : onboarding.agentStatus === "ERROR" && !setUpAgent.isPending
      ? "We couldn't start your agent. Try again in a moment."
      : null;

  if (paid) {
    return (
      <OnboardingShell
        {...shell}
        path={path}
        step={2}
        title={setUpError ? "Your assistant needs another try" : `Setting up ${agentName}`}
        subtitle="It's ready to chat on the web. You can connect Slack, Telegram and other channels later."
        footerStart={
          <button type="button" className="af-btn af-btn-ghost" onClick={() => finish(null, home)}>
            I&apos;ll do this later
          </button>
        }
        footerEnd={
          setUpError ? (
            <button type="button" className="af-btn af-btn-primary af-btn-lg" onClick={() => choosePath()}>
              Try again
            </button>
          ) : undefined
        }
      >
        {setUpError ? <StepAlert>{setUpError}</StepAlert> : <p role="status">Creating your assistant…</p>}
      </OnboardingShell>
    );
  }

  return (
    <TelegramStep
      {...shell}
      agentName={agentName}
      botUsername={onboarding.telegramBotUsername ?? null}
      agent={ready ? { id: onboarding.agentId!, connectionId: onboarding.connectionId! } : null}
      setUpError={setUpError}
      hasAgent={!!agentId}
      onLater={() => finish(null, home)}
      onRetrySetUp={() => setUpAgent.mutate()}
      onContinue={(username) => {
        setTelegramUsername(username);
        if (allows("integrations")) setStage("gmail");
        else finish(username);
      }}
      isContinuing={complete.isPending}
      // Chatting on the web still offers Gmail, then opens Web Chat however that step ends.
      // An Agent whose setup failed goes straight to Web Chat: there is nothing to connect it to.
      onSkip={() => {
        if (!setUpError && allows("integrations")) {
          setReturnTo(chatHref);
          setStage("gmail");
          return;
        }
        setSkipping(true);
        complete.mutate(undefined, {
          onSuccess: () => router.push(chatHref),
          onError: () => setSkipping(false),
        });
      }}
      isSkipping={skipping}
      finishError={complete.isError}
    />
  );
}
