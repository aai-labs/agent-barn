"use client";

import { Loader2 } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { SettingsErrorText } from "@/components/settings/settings-error-text";
import { SettingsSection } from "@/components/settings/settings-section";
import { Fact } from "@/features/spend-limits/components/fact";

import { useAnomalyDetection, useUpdateAnomalyDetection } from "../hooks/use-anomaly-detection";
import { BASELINE_DAYS } from "../utils";

const WHAT_IT_DOES = `Each Agent's activity is compared with what is normal for that Agent over the last ${BASELINE_DAYS} days, and anything unusual is listed on the Agent's Unusual activity tab.`;
// Said before anyone turns checks on, so judging what was flagged later needs no second
// consent.
const BILLING = "Checks may use an AI model provider, and any cost is billed to that Agent's spend.";
const ALERTS =
  "Owners and Admins are emailed when something unusual is flagged, unless it is low severity or probably fine.";
const DETECTION_LABEL_ID = "unusual-activity-toggle-label";
const ALERTS_LABEL_ID = "unusual-activity-alerts-toggle-label";

function Switch({
  labelId,
  label,
  checked,
  disabled,
  onChange,
}: {
  labelId: string;
  label: string;
  checked: boolean;
  disabled: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-4">
      <span id={labelId} className="text-[0.9rem] font-medium" style={{ color: "var(--ink)" }}>
        {label}
      </span>
      <button
        type="button"
        role="switch"
        aria-labelledby={labelId}
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className="relative h-5 w-9 shrink-0 rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-50"
        style={{ backgroundColor: checked ? "var(--ink)" : "var(--line)" }}
      >
        <span
          className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white transition-transform ${checked ? "translate-x-4" : ""}`}
        />
      </button>
    </div>
  );
}

/** The Organization's opt-in to unusual activity checks, and whether what they flag is
 * emailed. Owners and Admins only. */
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

  // Each change is saved as soon as its toggle is flipped, as for the other on/off
  // settings; the billing note above them is read before checks are turned on.
  const pending = update.isPending ? update.variables : undefined;
  const enabled = pending?.enabled ?? settings.enabled;
  const alertsEnabled = pending?.alertsEnabled ?? settings.alertsEnabled;

  return (
    <SettingsSection title="Unusual activity checks" description={WHAT_IT_DOES}>
      <div className="flex flex-col gap-4">
        <p className="m-0 max-w-2xl text-[0.86rem]" style={{ color: "var(--ink-2)" }}>
          {WHAT_IT_DOES} {BILLING}
        </p>
        {settings.canManage ? (
          <Switch
            labelId={DETECTION_LABEL_ID}
            label="Check Agents for unusual activity"
            checked={enabled}
            disabled={update.isPending}
            onChange={(checked) => update.mutate({ enabled: checked })}
          />
        ) : (
          <dl className="m-0">
            <Fact label="Status">{settings.enabled ? "On" : "Off"}</Fact>
          </dl>
        )}
        <p className="m-0 max-w-2xl text-[0.86rem]" style={{ color: "var(--ink-2)" }}>
          {ALERTS}
        </p>
        {settings.canManage ? (
          // Nothing is flagged while checks are off, so there is nothing to email.
          <Switch
            labelId={ALERTS_LABEL_ID}
            label="Email Owners and Admins about unusual activity"
            checked={alertsEnabled}
            disabled={update.isPending || !enabled}
            onChange={(checked) => update.mutate({ alertsEnabled: checked })}
          />
        ) : (
          <dl className="m-0">
            {/* Nothing is emailed while checks are off, whatever the setting says. */}
            <Fact label="Emails">{settings.enabled && settings.alertsEnabled ? "On" : "Off"}</Fact>
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
