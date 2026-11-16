"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { SettingsErrorText } from "@/components/settings/settings-error-text";
import { SettingsSection } from "@/components/settings/settings-section";
import { Checkbox } from "@/components/ui/checkbox";
import { Fact } from "@/features/spend-limits/components/fact";

import { useAnomalyDetection, useUpdateAnomalyDetection } from "../hooks/use-anomaly-detection";
import { BASELINE_DAYS } from "../utils";

const WHAT_IT_DOES = `Each Agent's activity is compared with what is normal for that Agent over the last ${BASELINE_DAYS} days, and anything unusual is listed on the Agent's Anomalies tab.`;
// Said before anyone turns checks on, so judging what was flagged later needs no second
// consent.
const BILLING = "Checks may use an AI model provider, and any cost is billed to that Agent's spend.";

/** The Organization's opt-in to unusual activity checks. Owners and Admins only. */
export function UnusualActivityPanel() {
  const { settings, isLoading, error, refetch } = useAnomalyDetection();
  const update = useUpdateAnomalyDetection();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<boolean | null>(null);

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

  const enabled = draft ?? settings.enabled;

  function reset() {
    setDraft(null);
    update.reset();
  }

  return (
    <SettingsSection
      title="Unusual activity checks"
      description={WHAT_IT_DOES}
      canEdit={settings.canManage}
      editing={editing}
      onEdit={() => setEditing(true)}
      onCancel={() => {
        reset();
        setEditing(false);
      }}
      onApply={async () => {
        await update.mutateAsync(enabled);
        reset();
      }}
      onApplied={() => setEditing(false)}
      applyDisabled={enabled === settings.enabled || update.isPending}
      applyLabel="Save"
      applyPendingLabel="Saving…"
      errorsShownInline
      confirm={
        enabled
          ? {
              title: "Turn on unusual activity checks?",
              description: `${WHAT_IT_DOES} ${BILLING}`,
              confirmLabel: "Turn on",
            }
          : {
              title: "Turn off unusual activity checks?",
              description:
                "Agents stop being checked. What was already flagged stays on each Agent's Anomalies tab.",
              confirmLabel: "Turn off",
            }
      }
    >
      <div className="flex max-w-2xl flex-col gap-4">
        <p className="m-0 text-[0.86rem]" style={{ color: "var(--ink-2)" }}>
          {WHAT_IT_DOES} {BILLING}
        </p>
        {editing && settings.canManage ? (
          <label className="flex items-center gap-2.5 text-[0.9rem]" style={{ color: "var(--ink)" }}>
            <Checkbox checked={enabled} onCheckedChange={(checked) => setDraft(checked === true)} />
            Check Agents for unusual activity
          </label>
        ) : (
          <dl className="m-0">
            <Fact label="Status">{settings.enabled ? "On" : "Off"}</Fact>
          </dl>
        )}
        {update.error && (
          <SettingsErrorText>{update.error instanceof Error ? update.error.message : "Save failed"}</SettingsErrorText>
        )}
      </div>
    </SettingsSection>
  );
}
