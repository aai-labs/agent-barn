"use client";

import { useId, useState } from "react";
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
import { MoneyInput } from "@/features/spend-limits/components/money-input";

import {
  DEFAULT_SPEND_LIMIT_WINDOW,
  SPEND_LIMIT_WINDOWS,
  amountError,
  formatRenewal,
  formatUsage,
  formatUsd,
  parseAmount,
  windowLabel,
} from "../spend-limit";

const UNCOVERED_REASON: Record<AgentLlmCoverage["status"], string> = {
  enrolled: "covered",
  unenrolled: "not enrolled",
  other_team: "already assigned elsewhere",
  unknown_key: "credentials not recognized",
  unreadable: "could not be checked",
};

export function LlmBudgetCard({ organization }: { organization: PlatformOrganization }) {
  const storedAmount = organization.llmBudgetUsd == null ? "" : String(organization.llmBudgetUsd);
  const storedWindow = organization.llmBudgetDuration ?? DEFAULT_SPEND_LIMIT_WINDOW;
  const [amount, setAmount] = useState(storedAmount);
  const [duration, setDuration] = useState(storedWindow);
  const [touched, setTouched] = useState(false);
  const renewalLabelId = useId();
  const hintId = useId();
  // Shown beside the controls rather than as a toast: a 502 means "saved, not applied
  // yet", which the administrator needs to read next to the amount it is about.
  const setBudget = useSetOrganizationLlmBudget(organization.id, { toastOnError: false });
  const { coverage, isLoading: coverageLoading } = useOrganizationLlmCoverage(organization.id);
  const enroll = useEnrollOrganizationLlmKeys(organization.id);

  const parsed = parseAmount(amount);
  // Required: an organization can no longer be left without a limit.
  const error = amountError(amount, { required: true });
  const unchanged = amount.trim() === storedAmount && duration === storedWindow;
  const busy = setBudget.isPending;
  const ceiling = organization.llmBudgetUsd;
  const own = organization.llmOwnBudgetUsd;
  const inForce = own ?? ceiling;

  const uncoveredCount = coverage ? coverage.totalAgents - coverage.enrolledAgents : 0;
  const spend = coverage?.spendUsd;
  const exhausted = inForce != null && spend != null && spend >= inForce;

  return (
    <div className="af-card p-4 mb-9">
      <h2
        className="m-0 flex items-center gap-2 text-[16px] font-semibold"
        style={{ color: "var(--ink)" }}
      >
        <Wallet width={15} height={15} aria-hidden /> Model spend limit
      </h2>
      <p className="m-0 mt-1 mb-3 text-[13px]" style={{ color: "var(--ink-3)" }}>
        {ceiling != null && `The most this organization can spend is ${formatUsd(ceiling)} ${windowLabel(storedWindow)}. `}
        {own != null
          ? `It has set its own lower limit of ${formatUsd(own)}, which is the one in force.`
          : "It can set a lower limit of its own, but never a higher one."}
      </p>

      <div className="flex flex-wrap items-end gap-2">
        <MoneyInput
          label="Spend limit"
          value={amount}
          onChange={setAmount}
          onBlur={() => setTouched(true)}
          disabled={busy}
          error={touched ? error : null}
          describedBy={hintId}
        />

        <div className="flex flex-col gap-1.5">
          <span id={renewalLabelId} className="text-[0.84rem] font-medium" style={{ color: "var(--ink)" }}>
            Renewal period
          </span>
          <Select value={duration} disabled={busy} onValueChange={setDuration}>
            <SelectTrigger
              className="af-input !h-auto"
              style={{ width: 180 }}
              aria-labelledby={renewalLabelId}
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {SPEND_LIMIT_WINDOWS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </div>

        <button
          className="af-btn af-btn-primary"
          disabled={busy || !!error || unchanged}
          onClick={() => {
            if (parsed === null || Number.isNaN(parsed)) return;
            setBudget.mutate(
              { budgetUsd: parsed, budgetDuration: duration },
              { onSuccess: () => setTouched(false) },
            );
          }}
        >
          {busy && <Loader2 width={14} height={14} className="animate-spin" />} Save
        </button>
      </div>

      <p id={hintId} className="m-0 mt-2 text-[0.8rem]" style={{ color: "var(--ink-3)" }}>
        Every limit beneath this one renews on the same schedule. For no practical limit, enter a very
        large amount.
      </p>

      {setBudget.error && (
        <p className="m-0 mt-2 text-xs" role="alert" style={{ color: "var(--err)" }}>
          {setBudget.error instanceof Error ? setBudget.error.message : "We couldn't update the spend limit."}
        </p>
      )}

      {inForce != null && !coverageLoading && (
        <p
          className="m-0 mt-2 text-[12.5px]"
          style={{ color: exhausted ? "var(--err)" : "var(--ink-3)" }}
        >
          {spend == null
            ? "Spend against this limit is unavailable right now."
            : `${formatUsage(spend, inForce)} used${exhausted ? " — limit reached" : ""}${
                coverage?.renewsAt ? `. Renews ${formatRenewal(coverage.renewsAt)}` : ""
              }.`}
        </p>
      )}

      {!!coverage && uncoveredCount > 0 && (
        <EnrollmentGate
          uncovered={coverage.uncovered}
          uncoveredCount={uncoveredCount}
          total={coverage.totalAgents}
          busy={enroll.isPending}
          onEnroll={() => enroll.mutate()}
        />
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
      className="mt-3 rounded-lg p-3"
      style={{ background: "var(--bg-soft)", border: "1px solid var(--line)" }}
    >
      <p
        className="m-0 flex items-center gap-2 text-[13px] font-medium"
        style={{ color: "var(--ink)" }}
      >
        <AlertTriangle width={14} height={14} />
        {/* One expression, not interleaved text nodes: inside a flex container the
            whitespace between them is not reliably preserved. */}
        <span>{`${uncoveredCount} of ${total} Agents aren't covered by this limit yet`}</span>
      </p>
      <p className="m-0 mt-1 text-[12.5px]" style={{ color: "var(--ink-3)" }}>
        Agents created before this organization had a spend limit aren&apos;t bound by it.
        Enroll them so the limit applies to them too.
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
        {busy && <Loader2 width={14} height={14} className="animate-spin" />} Enroll Agents
      </button>
    </div>
  );
}
