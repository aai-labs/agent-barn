"use client";

import { useState } from "react";

import { FormField, TokenInput } from "@/features/agents/components/hire-dialog-primitives";
import { useAgent } from "@/features/agents/hooks/use-agent";
import { useStartAgent } from "@/features/agents/hooks/use-start-agent";
import { useStopAgent } from "@/features/agents/hooks/use-stop-agent";
import { useUpdateAgent } from "@/features/agents/hooks/use-update-agent";
import { useValidateIntegration } from "@/features/agents/hooks/use-validate-integration";
import { getIntegrationProvider } from "@/features/agents/integrations";
import { getErrorDisplay } from "@/shared/api/error/get-error-display";

import { OnboardingShell, StepAlert, StepStatus, type OnboardingPath } from "./onboarding-shell";

const PROVIDER = "gmail_app_password";
const fields = getIntegrationProvider(PROVIDER)?.fields ?? [];
const addressField = fields.find((field) => field.key === "email");
const passwordField = fields.find((field) => field.key === "appPassword");

type Failure = { message: string; restartOnly: boolean };

/**
 * Optional step 4 of both paths: connect Gmail with an app password once the Agent exists.
 *
 * Saving follows the agent settings page: an Agent is stopped to change its credentials and
 * started again to pick them up. Updates do not check credentials with the provider, so the
 * sign-in is checked straight after saving, and a rejected password is removed again before
 * the restart, never left on the Agent.
 */
export function GmailStep({
  email,
  creditUsd,
  path,
  agentId,
  onDone,
  onLater,
}: {
  email: string;
  creditUsd: number | null;
  path: OnboardingPath;
  agentId: string;
  onDone: () => void;
  onLater: () => void;
}) {
  const [address, setAddress] = useState("");
  const [appPassword, setAppPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [saving, setSaving] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);
  const agent = useAgent(agentId);
  const stopAgent = useStopAgent();
  const updateAgent = useUpdateAgent();
  const validate = useValidateIntegration();
  const startAgent = useStartAgent();

  async function restart() {
    try {
      await startAgent.mutateAsync(agentId);
      return true;
    } catch {
      setFailure({ message: "We couldn't restart your agent. Try again.", restartOnly: true });
      return false;
    }
  }

  async function connect() {
    setSaving(true);
    setFailure(null);
    let stopped = false;
    try {
      const { data: current } = await agent.refetch();
      if (current?.status === "RUNNING") {
        await stopAgent.mutateAsync(agentId);
        stopped = true;
      }
      await updateAgent.mutateAsync({
        agentId,
        secrets: [{ provider: PROVIDER, content: { email: address.trim(), appPassword } }],
      });
      let rejected: string | null = null;
      try {
        const { result } = await validate.mutateAsync({ agentId, provider: PROVIDER });
        if (result.validationStatus === "invalid") {
          rejected = result.validationError ?? "Gmail didn't accept this address and app password.";
        }
      } catch (error) {
        rejected = getErrorDisplay(error).description;
      }
      if (rejected) await updateAgent.mutateAsync({ agentId, removedSecretProviders: [PROVIDER] });
      if (stopped && !(await restart())) return;
      if (rejected) {
        setFailure({ message: rejected, restartOnly: false });
        return;
      }
      onDone();
    } catch (error) {
      // Gmail was not saved; start the Agent again as it was, if this step stopped it.
      if (stopped && !(await restart())) return;
      setFailure({ message: `We couldn't connect Gmail: ${getErrorDisplay(error).description}`, restartOnly: false });
    } finally {
      setSaving(false);
    }
  }

  async function retryRestart() {
    setSaving(true);
    setFailure(null);
    try {
      if (await restart()) onDone();
    } finally {
      setSaving(false);
    }
  }

  const canConnect = address.trim() !== "" && appPassword.trim() !== "" && !saving;

  return (
    <OnboardingShell
      step={3}
      path={path}
      email={email}
      creditUsd={creditUsd}
      title="Let your agent read your Gmail"
      subtitle="Optional. Your agent can read your inbox, but never send, delete or change mail, and it never sees the app password."
      footerStart={
        <button type="button" className="af-btn af-btn-ghost" disabled={saving} onClick={onLater}>
          I&apos;ll do this later
        </button>
      }
      footerEnd={
        failure?.restartOnly ? (
          <button type="button" className="af-btn af-btn-primary af-btn-lg" disabled={saving} onClick={() => void retryRestart()}>
            Try again
          </button>
        ) : (
          <>
            <button type="button" className="af-btn af-btn-ghost" disabled={saving} onClick={onDone}>
              Skip
            </button>
            <button type="button" className="af-btn af-btn-primary af-btn-lg" disabled={!canConnect} onClick={() => void connect()}>
              {saving ? "Connecting…" : "Connect Gmail"}
            </button>
          </>
        )
      }
    >
      <div className="flex max-w-md flex-col gap-4">
        <FormField label={addressField?.label ?? "Gmail address"}>
          <input
            aria-label={addressField?.label ?? "Gmail address"}
            className="af-input"
            type="email"
            autoComplete="email"
            placeholder={addressField?.placeholder}
            value={address}
            disabled={saving || !!failure?.restartOnly}
            onChange={(event) => setAddress(event.target.value)}
          />
        </FormField>
        <FormField label={passwordField?.label ?? "App password"} hint={passwordField?.hint}>
          <TokenInput
            ariaLabel={passwordField?.label ?? "App password"}
            value={appPassword}
            onChange={setAppPassword}
            visible={showPassword}
            onToggle={() => setShowPassword((shown) => !shown)}
            placeholder={passwordField?.placeholder}
            disabled={saving || !!failure?.restartOnly}
          />
        </FormField>
        {saving && <StepStatus>Connecting Gmail and restarting your agent…</StepStatus>}
        {failure && <StepAlert>{failure.message}</StepAlert>}
      </div>
    </OnboardingShell>
  );
}
