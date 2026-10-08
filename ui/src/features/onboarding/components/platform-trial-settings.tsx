"use client";

import { useState } from "react";
import { Pencil } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { formatUsd, parseAmount } from "@/features/organizations/spend-limit";
import { getErrorDisplay } from "@/shared/api/error/get-error-display";

import { useTrialSettings } from "../hooks/use-trial-settings";

// Match the API's bounds: they only stop a typo from granting a fortune.
const MAX_CREDIT_USD = 10_000;
const MAX_AGENT_LIMIT = 50;

type Draft = { credit: string; agentLimit: string };

function agentsLabel(count: number) {
  return `${count} ${count === 1 ? "agent" : "agents"}`;
}

function parseAgentLimit(raw: string): number | null {
  const parsed = Number(raw.trim());
  return Number.isInteger(parsed) && parsed >= 1 && parsed <= MAX_AGENT_LIMIT ? parsed : null;
}

/** The Trials section of the platform settings page: what every trial organization gets. */
export function PlatformTrialSettings() {
  const {
    trialSettings,
    isLoadingTrialSettings,
    trialSettingsError,
    reloadTrialSettings,
    saveSettings,
    isSaving,
    saveError,
    resetSave,
  } = useTrialSettings();
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saved, setSaved] = useState(false);

  if (isLoadingTrialSettings) return <p className="m-0">Loading trial settings…</p>;
  if (trialSettingsError || !trialSettings)
    return (
      <AppErrorState
        error={trialSettingsError}
        title="Could not load trial settings"
        onRetry={() => void reloadTrialSettings()}
      />
    );

  const credit = draft === null ? null : parseAmount(draft.credit);
  const creditInvalid = draft !== null && (credit === null || Number.isNaN(credit) || credit > MAX_CREDIT_USD);
  const agentLimit = draft === null ? null : parseAgentLimit(draft.agentLimit);
  const agentLimitInvalid = draft !== null && agentLimit === null;
  const unchanged = credit === trialSettings.creditUsd && agentLimit === trialSettings.agentLimit;

  function change(next: Partial<Draft>) {
    setDraft((current) => (current ? { ...current, ...next } : current));
    setSaved(false);
    resetSave();
  }

  async function submit() {
    if (credit === null || Number.isNaN(credit) || agentLimit === null) return;
    try {
      await saveSettings({ creditUsd: credit, agentLimit });
      setDraft(null);
      setSaved(true);
    } catch {
      /* The error stays beside the fields. */
    }
  }

  return (
    <section className="af-card overflow-hidden" aria-label="Trial settings">
      <div className="p-5">
        {draft !== null ? (
          <div className="flex flex-col gap-5">
            <div>
              <label className="mb-2 block text-sm font-medium" htmlFor="trial-credit">
                Trial credit (USD)
              </label>
              <input
                id="trial-credit"
                inputMode="decimal"
                className="af-input max-w-[12rem]"
                value={draft.credit}
                aria-invalid={creditInvalid}
                onChange={(event) => change({ credit: event.target.value })}
              />
              {creditInvalid && (
                <p className="mt-2 text-sm" style={{ color: "var(--err)" }}>
                  Enter an amount from $0 to {formatUsd(MAX_CREDIT_USD, 0)}.
                </p>
              )}
              <p className="mb-0 mt-2 text-sm" style={{ color: "var(--ink-3)" }}>
                New trials start with this much to spend on their agents. It is granted once and doesn&apos;t
                renew; when it runs out, their agents stop replying. Trials that already exist keep theirs.
              </p>
            </div>
            <div>
              <label className="mb-2 block text-sm font-medium" htmlFor="trial-agent-limit">
                Agents per trial
              </label>
              <input
                id="trial-agent-limit"
                inputMode="numeric"
                className="af-input max-w-[8rem]"
                value={draft.agentLimit}
                aria-invalid={agentLimitInvalid}
                onChange={(event) => change({ agentLimit: event.target.value })}
              />
              {agentLimitInvalid && (
                <p className="mt-2 text-sm" style={{ color: "var(--err)" }}>
                  Enter a whole number from 1 to {MAX_AGENT_LIMIT}.
                </p>
              )}
              <p className="mb-0 mt-2 text-sm" style={{ color: "var(--ink-3)" }}>
                Applies to every trial straight away. A trial already over a lower limit keeps its agents but
                can&apos;t hire more.
              </p>
            </div>
          </div>
        ) : (
          <dl className="m-0 grid gap-x-8 gap-y-5 sm:grid-cols-2">
            <div>
              <dt
                className="mb-2 text-[0.7rem] font-semibold uppercase tracking-[0.08em]"
                style={{ color: "var(--ink-4)" }}
              >
                Trial credit
              </dt>
              <dd className="m-0 text-[0.9rem]" data-testid="saved-trial-credit">
                {formatUsd(trialSettings.creditUsd)}
              </dd>
              <dd className="mb-0 ml-0 mt-1 text-xs" style={{ color: "var(--ink-3)" }}>
                Granted once per trial; never renews
              </dd>
            </div>
            <div>
              <dt
                className="mb-2 text-[0.7rem] font-semibold uppercase tracking-[0.08em]"
                style={{ color: "var(--ink-4)" }}
              >
                Agents per trial
              </dt>
              <dd className="m-0 text-[0.9rem]" data-testid="saved-trial-agent-limit">
                {agentsLabel(trialSettings.agentLimit)}
              </dd>
            </div>
          </dl>
        )}
        {saveError && (
          <p className="mt-3 text-sm" role="alert" style={{ color: "var(--err)" }}>
            {getErrorDisplay(saveError).description}
          </p>
        )}
        {saved && (
          <p className="mb-0 mt-3 text-sm" role="status">
            Trial settings saved.
          </p>
        )}
      </div>
      <footer className="flex flex-wrap justify-end gap-2 border-t px-5 py-3" style={{ borderColor: "var(--line)" }}>
        {draft !== null ? (
          <>
            <button
              className="af-btn"
              disabled={isSaving}
              onClick={() => {
                setDraft(null);
                resetSave();
              }}
            >
              Cancel
            </button>
            <button
              className="af-btn af-btn-primary"
              disabled={creditInvalid || agentLimitInvalid || isSaving || unchanged}
              onClick={() => void submit()}
            >
              {isSaving ? "Saving…" : "Save"}
            </button>
          </>
        ) : (
          <button
            className="af-btn"
            onClick={() => {
              setDraft({ credit: String(trialSettings.creditUsd), agentLimit: String(trialSettings.agentLimit) });
              setSaved(false);
            }}
          >
            <Pencil size={14} /> Edit
          </button>
        )}
      </footer>
    </section>
  );
}
