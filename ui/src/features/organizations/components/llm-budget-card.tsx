"use client";

import { useState } from "react";
import { AlertTriangle, Loader2, Wallet } from "lucide-react";

import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import {
  useEnrollOrganizationLlmKeys,
  useOrganizationLlmCoverage,
  useSetOrganizationLlmBudget,
} from "../hooks/use-organization-actions";
import type { AgentLlmCoverage, PlatformOrganization } from "../schemas";

const DEFAULT_DURATION = "30d";

const DURATIONS = [
  { value: "1d", label: "per day" },
  { value: "7d", label: "per 7 days" },
  { value: "30d", label: "per 30 days" },
];

const UNCOVERED_REASON: Record<AgentLlmCoverage["status"], string> = {
  enrolled: "covered",
  unenrolled: "not enrolled",
  other_team: "already assigned elsewhere",
  unknown_key: "credentials not recognised",
  unreadable: "could not be checked",
};

/** Both halves of "X of Y used" share a precision chosen from the limit. Formatting
 *  them independently renders 0.011985 against a 0.01 cap as "$0.01 of $0.01", which
 *  hides the overshoot at exactly the point it matters. */
function usdDigits(limit: number) {
  return limit > 0 && limit < 1 ? 4 : 2;
}

function formatUsd(value: number, digits: number) {
  return `$${value.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

function formatRenewal(iso: string) {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

const durationLabel = (value: string | null | undefined) =>
  DURATIONS.find((d) => d.value === value)?.label ?? `per ${value}`;

/** Null means no cap. Zero is a real allowance of nothing, so it is never coalesced. */
function describeBudget(organization: PlatformOrganization) {
  if (organization.llmBudgetUsd == null) return "no limit";
  return `$${organization.llmBudgetUsd.toLocaleString()} ${durationLabel(organization.llmBudgetDuration)}`;
}

export function LlmBudgetCard({ organization }: { organization: PlatformOrganization }) {
  const [amount, setAmount] = useState(
    organization.llmBudgetUsd == null ? "" : String(organization.llmBudgetUsd),
  );
  const [duration, setDuration] = useState(organization.llmBudgetDuration ?? DEFAULT_DURATION);
  const setBudget = useSetOrganizationLlmBudget(organization.id);
  const {
    coverage,
    isLoading: coverageLoading,
    error: coverageError,
  } = useOrganizationLlmCoverage(organization.id);
  const enroll = useEnrollOrganizationLlmKeys(organization.id);

  const trimmed = amount.trim();
  const parsed = trimmed === "" ? null : Number(trimmed);
  const invalid = parsed !== null && (!Number.isFinite(parsed) || parsed < 0);
  const busy = setBudget.isPending;
  const hasLimit = organization.llmBudgetUsd != null;

  // An Agent whose key carries no team is not bound by the team's budget, so a limit
  // set now would quietly not apply to it. Gate the controls rather than let an
  // administrator configure a cap that does nothing.
  const uncoveredCount = coverage ? coverage.totalAgents - coverage.enrolledAgents : 0;
  // Unknown coverage gates too. Letting a failed check fall through to the controls
  // would set a limit over agents it might silently miss — the opposite of what the
  // gate is for. An organization that already has a limit is never gated out.
  const coverageUnknown = !coverageLoading && (!!coverageError || !coverage);
  const gated = !hasLimit && (coverageUnknown || (!!coverage && uncoveredCount > 0));
  const spend = coverage?.spendUsd;
  const exhausted =
    hasLimit && spend != null && organization.llmBudgetUsd != null && spend >= organization.llmBudgetUsd;

  return (
    <div className="af-card p-4 mb-9">
      <h2
        className="m-0 flex items-center gap-2 text-[16px] font-semibold"
        style={{ color: "var(--ink)" }}
      >
        <Wallet width={15} height={15} /> Model spend limit
      </h2>
      <p className="m-0 mt-1 mb-3 text-[13px]" style={{ color: "var(--ink-3)" }}>
        Currently {describeBudget(organization)}.{" "}
        {hasLimit
          ? "The organization can't see or change this, and its agents' model calls fail once the limit is reached."
          : "Set one to cap what this organization can spend on model calls."}
      </p>

      {gated && coverageUnknown ? (
        <p className="m-0 text-[13px]" style={{ color: "var(--err)" }}>
          We couldn&apos;t check which agents this limit would cover, so it can&apos;t be
          set right now. Try again shortly.
        </p>
      ) : gated && coverage ? (
        <EnrollmentGate
          uncovered={coverage.uncovered}
          uncoveredCount={uncoveredCount}
          total={coverage.totalAgents}
          busy={enroll.isPending}
          onEnroll={() => enroll.mutate()}
        />
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          {/* af-input/af-select in globals.css are unlayered, so their padding and
              width beat Tailwind utilities. Inline styles are what actually apply. */}
          <div className="relative" style={{ width: 150 }}>
            <span
              className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[13px]"
              style={{ color: "var(--ink-4)" }}
            >
              $
            </span>
            <input
              className="af-input"
              style={{ paddingLeft: 26 }}
              inputMode="decimal"
              placeholder="No limit"
              value={amount}
              disabled={busy}
              aria-label="Spend limit in USD"
              onChange={(event) => setAmount(event.target.value)}
            />
          </div>

          <Select
            value={duration}
            disabled={busy || trimmed === ""}
            onValueChange={setDuration}
          >
            <SelectTrigger
              className="af-input !h-auto"
              style={{ width: "10.5rem" }}
              aria-label="Budget window"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {DURATIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>

          <button
            className="af-btn af-btn-primary"
            disabled={busy || invalid}
            onClick={() =>
              setBudget.mutate({
                budgetUsd: parsed,
                budgetDuration: parsed === null ? null : duration,
              })
            }
          >
            {busy && <Loader2 width={14} height={14} className="animate-spin" />} Save
          </button>

          {/* Always available, even if coverage regresses: you must never be gated
              out of lifting a restriction. */}
          {hasLimit && (
            <button
              className="af-btn"
              disabled={busy}
              onClick={() =>
                setBudget.mutate(
                  { budgetUsd: null, budgetDuration: null },
                  { onSuccess: () => setAmount("") },
                )
              }
            >
              Remove limit
            </button>
          )}
        </div>
      )}

      {invalid && !gated && (
        <p className="m-0 mt-2 text-[12.5px]" style={{ color: "var(--err)" }}>
          Enter an amount of zero or more, or clear the field to remove the limit.
        </p>
      )}

      {hasLimit && !coverageLoading && (
        <p
          className="m-0 mt-2 text-[12.5px]"
          style={{ color: exhausted ? "var(--err)" : "var(--ink-3)" }}
        >
          {spend == null
            ? "Spend against this limit is unavailable right now."
            : `${formatUsd(spend, usdDigits(organization.llmBudgetUsd ?? 0))} of ${formatUsd(
                organization.llmBudgetUsd ?? 0,
                usdDigits(organization.llmBudgetUsd ?? 0),
              )} used${
                exhausted ? " — exhausted" : ""
              }${coverage?.renewsAt ? `. Renews ${formatRenewal(coverage.renewsAt)}` : ""}.`}
        </p>
      )}

      {!gated && !!coverage && uncoveredCount > 0 && (
        <p className="m-0 mt-2 text-[12.5px]" style={{ color: "var(--err)" }}>
          {uncoveredCount} of {coverage.totalAgents} agents are not covered by this limit.
        </p>
      )}
    </div>
  );
}

function EnrollmentGate({
  uncovered,
  uncoveredCount,
  total,
  busy,
  onEnroll,
}: {
  uncovered: AgentLlmCoverage[];
  uncoveredCount: number;
  total: number;
  busy: boolean;
  onEnroll: () => void;
}) {
  return (
    <div
      className="rounded-lg p-3"
      style={{ background: "var(--bg-soft)", border: "1px solid var(--line)" }}
    >
      <p
        className="m-0 flex items-center gap-2 text-[13px] font-medium"
        style={{ color: "var(--ink)" }}
      >
        <AlertTriangle width={14} height={14} />
        {/* One expression, not interleaved text nodes: inside a flex container the
            whitespace between them is not reliably preserved. */}
        <span>{`${uncoveredCount} of ${total} agents aren't enrolled yet`}</span>
      </p>
      <p className="m-0 mt-1 text-[12.5px]" style={{ color: "var(--ink-3)" }}>
        Agents created before this organization had a spend limit aren&apos;t bound by one.
        Enroll them first, or a limit set here won&apos;t apply to them.
      </p>

      <ul className="m-0 mt-2 list-none p-0 text-[12.5px]" style={{ color: "var(--ink-3)" }}>
        {uncovered.slice(0, 5).map((agent) => (
          <li key={agent.agentId} className="truncate">
            {agent.agentName} — {UNCOVERED_REASON[agent.status]}
          </li>
        ))}
        {uncovered.length > 5 && <li>and {uncovered.length - 5} more</li>}
      </ul>

      <button className="af-btn af-btn-primary mt-3" disabled={busy} onClick={onEnroll}>
        {busy && <Loader2 width={14} height={14} className="animate-spin" />} Enroll agents
      </button>
    </div>
  );
}
