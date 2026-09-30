"use client";

import Link from "next/link";
import { useState } from "react";
import { Loader2 } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { SettingsErrorText } from "@/components/settings/settings-error-text";
import { SettingsSection } from "@/components/settings/settings-section";
import {
  amountError,
  formatRenewal,
  formatUsage,
  formatUsd,
  parseAmount,
  periodLabel,
  windowLabel,
  zeroNotice,
} from "@/features/organizations/spend-limit";
import { Fact } from "@/features/spend-limits/components/fact";
import { MoneyInput } from "@/features/spend-limits/components/money-input";

import { useAgentLlmBudget, useSetAgentLlmBudget } from "../hooks/use-agent-llm-budget";
import type { AgentLlmBudget } from "../schemas";

const SOURCE: Record<AgentLlmBudget["source"], string> = {
  agent: "This Agent's own limit",
  default: "Default Agent limit",
  organization: "Organization limit",
};

export function AgentSpendLimitSettings({
  agentId,
  organizationId,
  editing,
  onEdit,
}: {
  agentId: string;
  organizationId: string;
  editing: boolean;
  onEdit: () => void;
}) {
  const { budget, isLoading, error, refetch } = useAgentLlmBudget(agentId);
  const setBudget = useSetAgentLlmBudget(agentId);
  // null means "untouched": the controls follow the server value until edited.
  const [amount, setAmount] = useState<string | null>(null);
  const [touched, setTouched] = useState(false);

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
        <Loader2 size={15} className="animate-spin" /> Loading spend limit…
      </div>
    );
  }
  if (error || !budget) {
    return (
      <AppErrorState error={error} title="We couldn't load this spend limit" onRetry={() => void refetch()} />
    );
  }

  const per = windowLabel(budget.window);
  // Empty means "follow the default Agent limit", the same rule as everywhere else.
  const value = amount ?? (budget.ownLimitUsd == null ? "" : String(budget.ownLimitUsd));
  const error_ = amountError(value, { max: budget.organizationLimitUsd });
  const next = parseAmount(value);
  const isDirty = !error_ && next !== (budget.ownLimitUsd ?? null);
  const limitsHref = `/dashboard/${organizationId}/settings?tab=spend-limits`;
  const nextLimit = next ?? budget.defaultLimitUsd;
  const renews = budget.renewsAt ? formatRenewal(budget.renewsAt) : null;
  const until = renews ? ` until ${renews}` : " until the limit renews";
  // Newly cut off: under its limit today, at or over it after the change.
  const stops =
    budget.spendUsd != null && budget.spendUsd < budget.limitUsd && budget.spendUsd >= nextLimit;

  function reset() {
    setAmount(null);
    setTouched(false);
    setBudget.reset();
  }

  return (
    <SettingsSection
      title="Model spend limit"
      description="The most this Agent can spend on model calls."
      canEdit={budget.canManage}
      editing={editing}
      onEdit={onEdit}
      onApply={async () => {
        await setBudget.mutateAsync(next);
        reset();
      }}
      onCancel={() => {
        reset();
        onEdit();
      }}
      onApplied={onEdit}
      applyDisabled={!isDirty || setBudget.isPending}
      errorsShownInline
      applyLabel="Save limit"
      applyPendingLabel="Saving…"
      confirm={{
        title: "Change this Agent's spend limit?",
        description: (
          <>
            <span className="block">
              {next === null
                ? `It will follow the default Agent limit of ${formatUsd(budget.defaultLimitUsd)} ${per} straight away.`
                : `It will be limited to ${formatUsd(next)} ${per} straight away.`}
            </span>
            {stops && (
              <span className="mt-1 block">
                {`It has already spent ${formatUsd(budget.spendUsd as number)} ${periodLabel(budget.window)}, so it will stop making model calls${until}.`}
              </span>
            )}
          </>
        ),
        destructive: stops,
        confirmLabel: stops ? "Lower limit and stop Agent" : undefined,
      }}
    >
      {editing && budget.canManage ? (
        <div className="flex max-w-xl flex-col gap-2">
          <MoneyInput
            label="Agent limit"
            value={value}
            onChange={setAmount}
            onBlur={() => setTouched(true)}
            placeholder={formatUsd(budget.defaultLimitUsd).slice(1)}
            hint={
              zeroNotice(value, "this Agent") ??
              `Leave empty to use the default Agent limit (${formatUsd(budget.defaultLimitUsd)} ${per}). ` +
                `Up to your organization limit of ${formatUsd(budget.organizationLimitUsd)} ${per}.`
            }
            error={touched || amount !== null ? error_ : null}
            action={
              value.trim() !== "" && (
                <button
                  type="button"
                  className="text-[0.84rem] underline underline-offset-2"
                  style={{ color: "var(--ink-2)" }}
                  onClick={() => setAmount("")}
                >
                  Use the default
                </button>
              )
            }
          />
          {setBudget.error && (
            <SettingsErrorText>
              {setBudget.error instanceof Error ? setBudget.error.message : "Save failed"}
            </SettingsErrorText>
          )}
        </div>
      ) : (
        <div className="flex flex-col gap-4">
        {budget.state === "exhausted" && (
          <p role="status" className="m-0 text-[0.88rem]" style={{ color: "var(--err)" }}>
            {`This Agent has reached its limit and can't make model calls${until}.`}{" "}
            {budget.canManage &&
              (budget.source === "agent" ? (
                <button type="button" className="underline underline-offset-2" onClick={onEdit}>
                  Raise its limit
                </button>
              ) : (
                <Link href={limitsHref} className="underline underline-offset-2">
                  Raise the limit in Spend limits
                </Link>
              ))}
          </p>
        )}
        <dl className="grid gap-x-8 gap-y-4 sm:grid-cols-2">
          <Fact label="Limit in force">
            {formatUsd(budget.limitUsd)} {per}
          </Fact>
          <Fact label="Set by">
            {budget.source === "agent" || !budget.canManage ? (
              SOURCE[budget.source]
            ) : (
              <Link
                href={limitsHref}
                className="underline underline-offset-2"
                style={{ color: "var(--ink)" }}
                aria-label={`${SOURCE[budget.source]}, set in Settings → Spend limits`}
              >
                {SOURCE[budget.source]}
              </Link>
            )}
          </Fact>
          <Fact label={`Spent ${periodLabel(budget.window)}`}>
            <span style={{ color: budget.state === "exhausted" ? "var(--err)" : undefined }}>
              {budget.spendUsd == null
                ? "Not available yet"
                : `${formatUsage(budget.spendUsd, budget.limitUsd)}${budget.state === "exhausted" ? " — limit reached" : ""}`}
            </span>
          </Fact>
          <Fact label="Renews">{renews ?? "—"}</Fact>
        </dl>
        </div>
      )}
    </SettingsSection>
  );
}
