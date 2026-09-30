"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { SettingsErrorText } from "@/components/settings/settings-error-text";
import { SettingsSection } from "@/components/settings/settings-section";
import { useAgentSettings } from "@/features/agent-settings/hooks/use-agent-settings";
import {
  useOrganizationLlmBudget,
  useSetOrganizationOwnLlmBudget,
} from "@/features/organizations/hooks/use-organization-llm-budget";
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

import { describeCascade } from "../cascade";
import { useAgentLlmBudgets } from "../hooks/use-agent-llm-budgets";
import { Fact } from "./fact";
import { MoneyInput } from "./money-input";

/** The organization's own limit beneath the most it is allowed. */
export function OrganizationLimitSection({ editing, onEdit }: { editing: boolean; onEdit: () => void }) {
  const { budget, isLoading, error, refetch } = useOrganizationLlmBudget();
  const { settings } = useAgentSettings();
  const { agents } = useAgentLlmBudgets();
  const setOwn = useSetOrganizationOwnLlmBudget({ toastOnError: false });
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
      <AppErrorState
        error={error}
        title="We couldn't load your organization's spend limit"
        onRetry={() => void refetch()}
      />
    );
  }

  const per = windowLabel(budget.window);
  // Empty means "follow the maximum", the same rule as the default Agent limit.
  const value = amount ?? (budget.ownLimitUsd == null ? "" : String(budget.ownLimitUsd));
  const error_ = amountError(value, { max: budget.ceilingUsd });
  const next = parseAmount(value);
  const isDirty = !error_ && next !== (budget.ownLimitUsd ?? null);
  const inForceAfter = next ?? budget.ceilingUsd;
  const cascade = describeCascade({
    next: inForceAfter,
    organizationSpendUsd: budget.spendUsd,
    ownDefault: settings?.defaultAgentLlmBudgetUsd ?? null,
    effectiveDefault: settings?.effectiveDefaultAgentLlmBudgetUsd ?? 0,
    agents: (agents ?? []).map((agent) => ({
      name: agent.agentName,
      limitUsd: agent.limitUsd,
      ownLimitUsd: agent.ownLimitUsd,
      spendUsd: agent.spendUsd,
    })),
    period: periodLabel(budget.window),
    renews: budget.renewsAt ? formatRenewal(budget.renewsAt) : null,
  });

  function reset() {
    setAmount(null);
    setTouched(false);
    setOwn.reset();
  }

  return (
    <SettingsSection
      title="Organization limit"
      description="The most your organization can spend on model calls."
      canEdit={budget.canManage}
      editing={editing}
      onEdit={onEdit}
      onApply={async () => {
        await setOwn.mutateAsync(next);
        reset();
      }}
      onCancel={() => {
        reset();
        onEdit();
      }}
      onApplied={onEdit}
      applyDisabled={!isDirty || setOwn.isPending}
      errorsShownInline
      applyLabel="Save limit"
      applyPendingLabel="Saving…"
      confirm={{
        title: "Change your organization's spend limit?",
        destructive: cascade.stopsAgents,
        confirmLabel: cascade.stopsAgents ? "Lower limit and stop Agents" : undefined,
        description: (
          <>
            <span className="block">
              Your organization will be limited to {formatUsd(inForceAfter)} {per}, straight away.
            </span>
            {cascade.lines.map((line) => (
              <span key={line} className="mt-1 block">
                {line}
              </span>
            ))}
          </>
        ),
      }}
    >
      {editing && budget.canManage ? (
        <div className="flex max-w-xl flex-col gap-2">
          <MoneyInput
            label="Your limit"
            value={value}
            onChange={setAmount}
            onBlur={() => setTouched(true)}
            placeholder={formatUsd(budget.ceilingUsd).slice(1)}
            hint={
              zeroNotice(value, "your organization's Agents") ??
              `Leave empty to use the most your organization is allowed (${formatUsd(budget.ceilingUsd)} ${per}).`
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
                  Use the maximum
                </button>
              )
            }
          />
          {setOwn.error && (
            <SettingsErrorText>
              {setOwn.error instanceof Error ? setOwn.error.message : "Save failed"}
            </SettingsErrorText>
          )}
        </div>
      ) : (
        <dl className="grid gap-x-8 gap-y-4 sm:grid-cols-2">
          <Fact label="Limit in force">
            {formatUsd(budget.limitUsd)} {per}
          </Fact>
          <Fact label="Set by">{budget.ownLimitUsd == null ? "The most you are allowed" : "This organization"}</Fact>
          <Fact label={`Spent ${periodLabel(budget.window)}`}>
            <span style={{ color: budget.state === "exhausted" ? "var(--err)" : undefined }}>
              {budget.spendUsd == null
                ? "Not available yet"
                : `${formatUsage(budget.spendUsd, budget.limitUsd)}${budget.state === "exhausted" ? " — limit reached" : ""}`}
            </span>
          </Fact>
          <Fact label="Renews">{budget.renewsAt ? formatRenewal(budget.renewsAt) : "—"}</Fact>
          <Fact label="Most you are allowed">
            {formatUsd(budget.ceilingUsd)} {per}
          </Fact>
        </dl>
      )}
    </SettingsSection>
  );
}
