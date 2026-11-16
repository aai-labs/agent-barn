"use client";

import { useId, useState } from "react";
import Link from "next/link";
import { Loader2 } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { Badge } from "@/components/badge";
import { SettingsErrorText } from "@/components/settings/settings-error-text";
import { SettingsSection } from "@/components/settings/settings-section";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { Agent } from "@/features/agents/schemas";
import { Fact } from "@/features/spend-limits/components/fact";
import { formatDate } from "@/shared/date";

import {
  ANOMALY_PAGE_SIZE,
  useAgentAnomalies,
  useAgentNormalBehaviour,
  useUpdateAnomalyOverride,
} from "../hooks/use-agent-anomalies";
import type { Anomaly, NormalBehaviour, Sensitivity } from "../schemas";
import {
  BASELINE_DAYS,
  MIN_ACTIVE_DAYS,
  SENSITIVITY_HINTS,
  SENSITIVITY_LABELS,
  SIGNAL_LABELS,
  formatSignalValue,
  isFirstUse,
  parseCap,
} from "../utils";

const DESTINATIONS_NOTE = "Destinations are the web addresses seen in tool calls.";

function Muted({ children }: { children: React.ReactNode }) {
  return (
    <p className="m-0 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
      {children}
    </p>
  );
}

function AnomalyRow({ anomaly }: { anomaly: Anomaly }) {
  const firstUse = isFirstUse(anomaly.signal);
  const ongoing = anomaly.endedAt === null;
  return (
    <li data-testid="anomaly" className="border-t px-5 py-3.5 first:border-t-0" style={{ borderColor: "var(--line)" }}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[0.92rem] font-medium" style={{ color: "var(--ink)" }}>
          {SIGNAL_LABELS[anomaly.signal]}
        </span>
        {anomaly.subject && (
          <span className="font-mono text-[0.84rem]" style={{ color: "var(--ink-2)" }}>
            {anomaly.subject}
          </span>
        )}
        {!firstUse && <Badge variant={ongoing ? "warn" : "neutral"}>{ongoing ? "Ongoing" : "Ended"}</Badge>}
      </div>
      <div className="mt-1 text-[0.8rem]" style={{ color: "var(--ink-3)" }}>
        {firstUse
          ? `First used ${formatDate(anomaly.startedAt)}`
          : [
              `${formatSignalValue(anomaly.signal, anomaly.observedValue)} at its highest`,
              anomaly.usualValue !== null
                ? `usually ${formatSignalValue(anomaly.signal, anomaly.usualValue)}`
                : anomaly.threshold !== null
                  ? `cap ${formatSignalValue(anomaly.signal, anomaly.threshold)}`
                  : null,
              `since ${formatDate(anomaly.startedAt)}`,
              ongoing ? null : `until ${formatDate(anomaly.endedAt as string)}`,
            ]
              .filter(Boolean)
              .join(" · ")}
      </div>
    </li>
  );
}

function FlaggedActivity({ agent, detectionEnabled }: { agent: Agent; detectionEnabled: boolean | undefined }) {
  const { anomalies, total, isLoading, error, refetch } = useAgentAnomalies(agent.id);
  return (
    <section className="af-card overflow-hidden" aria-label="Flagged activity">
      <header className="border-b px-5 py-3.5" style={{ borderColor: "var(--line)" }}>
        <h3 className="m-0 text-[0.98rem] font-semibold" style={{ color: "var(--ink)" }}>
          Flagged activity
        </h3>
        <Muted>
          What {agent.name} did that was unusual for it, most recent first. {DESTINATIONS_NOTE}
        </Muted>
      </header>
      {detectionEnabled === false && (
        <div className="border-b px-5 py-3 text-[0.86rem]" style={{ borderColor: "var(--line)", color: "var(--ink-2)" }}>
          Unusual activity checks are off for this organization.{" "}
          <Link className="underline" href={`/dashboard/${agent.organizationId}/settings?tab=unusual-activity`}>
            Turn them on in Settings
          </Link>
        </div>
      )}
      {isLoading ? (
        <div className="flex items-center gap-2 px-5 py-4 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
          <Loader2 size={15} className="animate-spin" /> Loading flagged activity…
        </div>
      ) : error || !anomalies ? (
        <AppErrorState error={error} title="We couldn't load flagged activity" onRetry={() => void refetch()} />
      ) : anomalies.length === 0 ? (
        <div className="px-5 py-4">
          <Muted>Nothing unusual has been flagged for {agent.name}.</Muted>
        </div>
      ) : (
        <>
          <ul className="m-0 list-none p-0">
            {anomalies.map((anomaly) => (
              <AnomalyRow key={anomaly.id} anomaly={anomaly} />
            ))}
          </ul>
          {total > ANOMALY_PAGE_SIZE && (
            <div className="border-t px-5 py-3" style={{ borderColor: "var(--line)" }}>
              <Muted>
                Showing the {ANOMALY_PAGE_SIZE} most recent of {total}.
              </Muted>
            </div>
          )}
        </>
      )}
    </section>
  );
}

function UsedList({ label, items, note }: { label: string; items: string[]; note?: string }) {
  return (
    <Fact label={label}>
      {items.length === 0 ? (
        <span style={{ color: "var(--ink-3)" }}>None</span>
      ) : (
        <span className="font-mono text-[0.84rem]">{items.join(", ")}</span>
      )}
      {note && (
        <span className="mt-0.5 block text-[0.78rem]" style={{ color: "var(--ink-3)" }}>
          {note}
        </span>
      )}
    </Fact>
  );
}

function capsSummary(normal: NormalBehaviour): string {
  const caps = [
    normal.override.maxLlmTokensPerHour !== null
      ? `${normal.override.maxLlmTokensPerHour.toLocaleString("en-US")} model tokens`
      : null,
    normal.override.maxLlmCallsPerHour !== null
      ? `${normal.override.maxLlmCallsPerHour.toLocaleString("en-US")} model calls`
      : null,
  ].filter(Boolean);
  return caps.length === 0 ? "No hourly caps" : `At most ${caps.join(" and ")} per hour`;
}

function CapInput({
  label,
  value,
  onChange,
  error,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  error: string | null;
}) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-[0.84rem] font-medium" style={{ color: "var(--ink-2)" }}>
        {label}
      </label>
      <Input id={id} inputMode="numeric" placeholder="No cap" value={value} onChange={(event) => onChange(event.target.value)} />
      {error && <SettingsErrorText>{error}</SettingsErrorText>}
    </div>
  );
}

function NormalBehaviourSection({ agent }: { agent: Agent }) {
  const { normal, isLoading, error, refetch } = useAgentNormalBehaviour(agent.id);
  const update = useUpdateAnomalyOverride(agent.id);
  const sensitivityLabelId = useId();
  const [editing, setEditing] = useState(false);
  const [sensitivity, setSensitivity] = useState<Sensitivity | null>(null);
  const [tokens, setTokens] = useState<string | null>(null);
  const [calls, setCalls] = useState<string | null>(null);

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
        <Loader2 size={15} className="animate-spin" /> Loading what&apos;s normal for {agent.name}…
      </div>
    );
  }
  if (error || !normal) {
    return <AppErrorState error={error} title="We couldn't load what's normal for this agent" onRetry={() => void refetch()} />;
  }

  const chosenSensitivity = sensitivity ?? normal.override.sensitivity;
  const tokensValue = tokens ?? (normal.override.maxLlmTokensPerHour?.toString() ?? "");
  const callsValue = calls ?? (normal.override.maxLlmCallsPerHour?.toString() ?? "");
  const tokensCap = parseCap(tokensValue);
  const callsCap = parseCap(callsValue);
  const invalid = Boolean(tokensCap.error || callsCap.error);
  const dirty =
    chosenSensitivity !== normal.override.sensitivity ||
    tokensCap.cap !== normal.override.maxLlmTokensPerHour ||
    callsCap.cap !== normal.override.maxLlmCallsPerHour;

  function reset() {
    setSensitivity(null);
    setTokens(null);
    setCalls(null);
    update.reset();
  }

  return (
    <SettingsSection
      title="Normal behaviour"
      description={`What ${agent.name} usually does, learned from its last ${BASELINE_DAYS} days.`}
      canEdit={normal.canManage}
      editing={editing}
      onEdit={() => setEditing(true)}
      onCancel={() => {
        reset();
        setEditing(false);
      }}
      onApply={async () => {
        await update.mutateAsync({
          sensitivity: chosenSensitivity,
          maxLlmTokensPerHour: tokensCap.cap,
          maxLlmCallsPerHour: callsCap.cap,
        });
        reset();
      }}
      onApplied={() => setEditing(false)}
      applyDisabled={!dirty || invalid || update.isPending}
      applyLabel="Save"
      applyPendingLabel="Saving…"
      errorsShownInline
      confirm={{
        title: `Change what's normal for ${agent.name}?`,
        description: "The next check uses the new sensitivity and caps. What was already flagged stays as it is.",
      }}
    >
      <div className="flex flex-col gap-5">
        <div>
          <h3 className="m-0 text-[0.98rem] font-semibold" style={{ color: "var(--ink)" }}>
            Normal behaviour
          </h3>
          <Muted>
            What {agent.name} usually does, learned from the hours it was active in the last {BASELINE_DAYS} days.
          </Muted>
        </div>

        {!normal.enoughHistory && (
          <Muted>
            Still learning what&apos;s normal for {agent.name}: nothing is flagged until it has been active on{" "}
            {MIN_ACTIVE_DAYS} different days ({normal.activeDays} so far). Hourly caps apply straight away.
          </Muted>
        )}

        {normal.rates.length > 0 && (
          <ul className="m-0 flex list-none flex-col gap-1.5 p-0" aria-label="Usual rates">
            {normal.rates.map((rate) => (
              <li key={rate.signal} className="text-[0.86rem]" style={{ color: "var(--ink-2)" }}>
                <span className="font-medium" style={{ color: "var(--ink)" }}>
                  {SIGNAL_LABELS[rate.signal]}
                </span>
                {` · usually ${formatSignalValue(rate.signal, rate.usual)}, flagged above ${formatSignalValue(rate.signal, rate.threshold)}`}
              </li>
            ))}
          </ul>
        )}

        <dl className="m-0 grid gap-x-8 gap-y-4 sm:grid-cols-2">
          <UsedList label="Tools" items={normal.tools} />
          <UsedList label="Integration actions" items={normal.integrationActions} />
          <UsedList label="Destinations" items={normal.destinations} note={DESTINATIONS_NOTE} />
        </dl>

        {editing && normal.canManage ? (
          <div className="flex max-w-xl flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <span id={sensitivityLabelId} className="text-[0.84rem] font-medium" style={{ color: "var(--ink-2)" }}>
                Sensitivity
              </span>
              <Select value={chosenSensitivity} onValueChange={(value) => setSensitivity(value as Sensitivity)}>
                <SelectTrigger aria-labelledby={sensitivityLabelId} className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {(["LOW", "NORMAL", "HIGH"] as const).map((option) => (
                      <SelectItem key={option} value={option}>
                        {SENSITIVITY_LABELS[option]}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
              <Muted>{SENSITIVITY_HINTS[chosenSensitivity]}</Muted>
            </div>
            <CapInput label="Most tokens per hour" value={tokensValue} onChange={setTokens} error={tokensCap.error} />
            <CapInput label="Most model calls per hour" value={callsValue} onChange={setCalls} error={callsCap.error} />
            <Muted>A cap is flagged whenever it is passed, whatever is usual.</Muted>
            {update.error && (
              <SettingsErrorText>{update.error instanceof Error ? update.error.message : "Save failed"}</SettingsErrorText>
            )}
          </div>
        ) : (
          <dl className="m-0 grid gap-x-8 gap-y-4 sm:grid-cols-2">
            <Fact label="Sensitivity">{SENSITIVITY_LABELS[normal.override.sensitivity]} sensitivity</Fact>
            <Fact label="Hourly caps">{capsSummary(normal)}</Fact>
          </dl>
        )}
      </div>
    </SettingsSection>
  );
}

/** Shown only to Organization Owners and Admins. */
export function AgentAnomaliesTab({ agent }: { agent: Agent }) {
  const { normal } = useAgentNormalBehaviour(agent.id);
  return (
    <div className="flex flex-col gap-6">
      <FlaggedActivity agent={agent} detectionEnabled={normal?.detectionEnabled} />
      <NormalBehaviourSection agent={agent} />
    </div>
  );
}
