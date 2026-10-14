"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";

import { AuthLoadingFallback } from "@/auth/components/auth-loading-fallback";
import { useCurrentUser } from "@/auth/providers/user-context-provider";
import { AppErrorState } from "@/components/app-error-state";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";
import { useOrgStore } from "@/features/organizations/stores/org-store";
import { getErrorDisplay } from "@/shared/api/error/get-error-display";

import { useOnboarding, useOnboardingActions } from "../hooks/use-onboarding";
import { DoneStep } from "./done-step";
import { OnboardingShell, StepAlert, StepHeading } from "./onboarding-shell";
import { TelegramStep } from "./telegram-step";

/** Steps 2 and 3, for someone signed in whose trial still needs setting up. */
export function OnboardingFlow() {
  const router = useRouter();
  const { user } = useCurrentUser();
  const { selectedOrganization } = useOrganizationContext();
  const setOrganizationId = useOrgStore((state) => state.setOrganizationId);
  const { onboarding, isLoadingOnboarding, onboardingError, reloadOnboarding } = useOnboarding();
  const { setUpAgent, complete } = useOnboardingActions();
  const [telegramUsername, setTelegramUsername] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const trialOrganizationId = onboarding?.organizationId ?? null;
  const required = onboarding?.required ?? false;

  // Nothing (left) to do here: the dashboard is home.
  useEffect(() => {
    if (onboarding && !required && !done) router.replace("/dashboard");
  }, [onboarding, required, done, router]);

  // Telegram linking acts in the trial's organization.
  useEffect(() => {
    if (trialOrganizationId && selectedOrganization?.id !== trialOrganizationId) {
      setOrganizationId(user.id, trialOrganizationId);
    }
  }, [trialOrganizationId, selectedOrganization?.id, setOrganizationId, user.id]);

  // Set up whatever is still missing, once per visit. It is safe to repeat, and also
  // restarts an Agent that stopped.
  const setUpRequested = useRef(false);
  useEffect(() => {
    if (!required || setUpRequested.current) return;
    setUpRequested.current = true;
    setUpAgent.mutate();
  }, [required, setUpAgent]);

  if (isLoadingOnboarding) return <AuthLoadingFallback message="Loading your account…" />;
  if (onboardingError)
    return (
      <AppErrorState
        error={onboardingError}
        title="We couldn't load your setup"
        onRetry={() => void reloadOnboarding()}
        className="min-h-svh"
      />
    );
  if (!onboarding || (!required && !done)) return <AuthLoadingFallback message="Opening your dashboard…" />;

  if (done) {
    return (
      <OnboardingShell step={3}>
        <DoneStep
          email={user.email}
          telegramUsername={telegramUsername}
          creditUsd={onboarding.creditUsd ?? null}
          botUsername={onboarding.telegramBotUsername ?? null}
          onDashboard={() => router.push(trialOrganizationId ? `/dashboard/${trialOrganizationId}` : "/dashboard")}
        />
      </OnboardingShell>
    );
  }

  const agentFailed = onboarding.agentStatus === "ERROR";
  // An Agent already running stays on screen while setup re-checks it: unmounting the
  // Telegram step mid-way would drop the link it is preparing.
  const ready =
    onboarding.agentStatus === "RUNNING" &&
    onboarding.agentId &&
    onboarding.connectionId &&
    selectedOrganization?.id === trialOrganizationId;

  return (
    <OnboardingShell step={2}>
      {ready && onboarding.agentId && onboarding.connectionId ? (
        <TelegramStep
          agentId={onboarding.agentId}
          connectionId={onboarding.connectionId}
          botUsername={onboarding.telegramBotUsername ?? null}
          isContinuing={complete.isPending}
          onContinue={(username) => {
            setTelegramUsername(username);
            complete.mutate(undefined, { onSuccess: () => setDone(true) });
          }}
        />
      ) : (
        <>
          <StepHeading title="Setting up your agent">This takes a few seconds.</StepHeading>
          {setUpAgent.isError || (agentFailed && !setUpAgent.isPending) ? (
            <div className="flex flex-col gap-4">
              <StepAlert>
                {setUpAgent.isError
                  ? `We couldn't set up your agent: ${getErrorDisplay(setUpAgent.error).description}`
                  : "We couldn't start your agent. Try again in a moment."}
              </StepAlert>
              <div>
                <button type="button" className="af-btn af-btn-lg" onClick={() => setUpAgent.mutate()}>
                  Try again
                </button>
              </div>
            </div>
          ) : (
            <p className="m-0 flex items-center gap-2 text-[13.5px]" role="status" style={{ color: "var(--ink-2)" }}>
              <Loader2 width={15} height={15} className="animate-spin" aria-hidden />
              Starting your agent…
            </p>
          )}
        </>
      )}
      {complete.isError && (
        <div className="mt-4">
          <StepAlert>We couldn&apos;t save your progress. Try again.</StepAlert>
        </div>
      )}
    </OnboardingShell>
  );
}
