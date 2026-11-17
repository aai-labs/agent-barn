"use client";

import { Loader2 } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { SettingsErrorText } from "@/components/settings/settings-error-text";
import { SettingsSection } from "@/components/settings/settings-section";
import { Fact } from "@/features/spend-limits/components/fact";

import { useAnomalyDetection, useUpdateAnomalyDetection } from "../hooks/use-anomaly-detection";
import { BASELINE_DAYS } from "../utils";

const WHAT_IT_DOES = `Each Agent's activity is compared with what is normal for that Agent over the last ${BASELINE_DAYS} days, and anything unusual is listed on the Agent's Anomalies tab.`;
// Said before anyone turns checks on, so judging what was flagged later needs no second
// consent.
const BILLING = "Checks may use an AI model provider, and any cost is billed to that Agent's spend.";
const TOGGLE_LABEL_ID = "unusual-activity-toggle-label";

/** The Organization's opt-in to unusual activity checks. Owners and Admins only. */
export function UnusualActivityPanel() {
  const { settings, isLoading, error, refetch } = useAnomalyDetection();
  const update = useUpdateAnomalyDetection();

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
        <Loader2 size={15} className="animate-spin" /> Loading unusual activity checks…
      </div>
    );
  }
  if (error || !settings) {
    return (
      <AppErrorState error={error} title="We couldn't load unusual activity checks" onRetry={() => void refetch()} />
    );
  }

  // The change is saved as soon as the toggle is flipped, as for the other on/off
  // settings; the billing note above it is read before checks are turned on.
  const enabled = update.isPending && update.variables !== undefined ? update.variables : settings.enabled;

  return (
    <SettingsSection title="Unusual activity checks" description={WHAT_IT_DOES}>
      <div className="flex max-w-2xl flex-col gap-4">
        <p className="m-0 text-[0.86rem]" style={{ color: "var(--ink-2)" }}>
          {WHAT_IT_DOES} {BILLING}
        </p>
        {settings.canManage ? (
          <div className="flex items-center justify-between gap-4">
            <span id={TOGGLE_LABEL_ID} className="text-[0.9rem] font-medium" style={{ color: "var(--ink)" }}>
              Check Agents for unusual activity
            </span>
            <button
              type="button"
              role="switch"
              aria-labelledby={TOGGLE_LABEL_ID}
              aria-checked={enabled}
              disabled={update.isPending}
              onClick={() => update.mutate(!enabled)}
              className="relative h-5 w-9 shrink-0 rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-50"
              style={{ backgroundColor: enabled ? "var(--ink)" : "var(--line)" }}
            >
              <span
                className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white transition-transform ${enabled ? "translate-x-4" : ""}`}
              />
            </button>
          </div>
        ) : (
          <dl className="m-0">
            <Fact label="Status">{settings.enabled ? "On" : "Off"}</Fact>
          </dl>
        )}
        {update.error && (
          <SettingsErrorText>
            {update.error instanceof Error ? update.error.message : "Changing unusual activity checks failed."}
          </SettingsErrorText>
        )}
      </div>
    </SettingsSection>
  );
}
