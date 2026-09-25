"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { SettingsErrorText } from "@/components/settings/settings-error-text";
import { SettingsSection } from "@/components/settings/settings-section";
import { useOrganizationLlmBudget } from "@/features/organizations/hooks/use-organization-llm-budget";
import {
  amountError,
  formatRenewal,
  formatUsd,
  parseAmount,
  periodLabel,
  windowLabel,
  zeroNotice,
} from "@/features/organizations/spend-limit";
import { useAgentLlmBudgets } from "@/features/spend-limits/hooks/use-agent-llm-budgets";
import { Fact } from "@/features/spend-limits/components/fact";
import { MoneyInput } from "@/features/spend-limits/components/money-input";

import { useAgentSettings } from "../hooks/use-agent-settings";
import { useUpdateAgentSettings } from "../hooks/use-update-agent-settings";

function plural(count: number, singular: string, plural_: string) {
  return `${count} ${count === 1 ? singular : plural_}`;
}

/** Names who a change reaches, from the server's counts. Unlike the default model,
 *  a spend limit applies straight away — no restart involved. */
function reach(inheriting: number, override: number, amount: number) {
  const followers =
    inheriting === 0
      ? "No Agents currently follow the default"
      : `${plural(inheriting, "Agent follows", "Agents follow")} the default and will be limited to ${formatUsd(amount)} straight away`;
  const own =
    override === 0 ? "" : ` ${plural(override, "Agent has", "Agents have")} their own limit and are unaffected.`;
  return `${followers}.${own}`;
}

export function AgentDefaultSpendLimitSection({ editing, onEdit }: { editing: boolean; onEdit: () => void }) {
  const { settings, isLoading, error, refetch } = useAgentSettings();
  const { budget } = useOrganizationLlmBudget();
  const { agents } = useAgentLlmBudgets();
  const updateSettings = useUpdateAgentSettings({ toastOnError: false });
  const [draft, setDraft] = useState<string | null>(null);
  const [touched, setTouched] = useState(false);

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
        <Loader2 size={15} className="animate-spin" /> Loading the default Agent limit…
      </div>
    );
  }
  if (error || !settings) {
    return (
      <AppErrorState error={error} title="We couldn't load the default Agent limit" onRetry={() => void refetch()} />
    );
  }

  const per = windowLabel(budget?.window);
  const organizationLimit = budget?.limitUsd;
  const canEdit = settings.canManageLlmBudget;
  const stored = settings.defaultAgentLlmBudgetUsd ?? null;
  const value = draft ?? (stored == null ? "" : String(stored));
  const error_ = amountError(value, { max: organizationLimit });
  const parsed = parseAmount(value);
  const isDirty = !error_ && parsed !== stored;
  const resulting = parsed ?? settings.effectiveDefaultAgentLlmBudgetUsd;
  // Agents following the default that are under it today and at or over it after.
  const stopped = (agents ?? []).filter(
    (agent) =>
      agent.source !== "agent" &&
      agent.spendUsd != null &&
      agent.spendUsd < agent.limitUsd &&
      agent.spendUsd >= resulting,
  );
  const renews = budget?.renewsAt ? ` until ${formatRenewal(budget.renewsAt)}` : " until the limit renews";

  function reset() {
    setDraft(null);
    setTouched(false);
    updateSettings.reset();
  }

  return (
    <SettingsSection
      title="Default Agent limit"
      description="The most an Agent can spend on model calls unless it has been given a limit of its own."
      canEdit={canEdit}
      editing={editing}
      onEdit={onEdit}
      onApply={async () => {
        await updateSettings.mutateAsync({ defaultAgentLlmBudgetUsd: parsed });
        reset();
      }}
      onCancel={() => {
        reset();
        onEdit();
      }}
      onApplied={onEdit}
      // Without the organization's limit there is nothing to check a new default against.
      applyDisabled={!isDirty || organizationLimit == null || updateSettings.isPending}
      errorsShownInline
      applyLabel="Change default"
      applyPendingLabel="Changing…"
      confirm={{
        title: "Change the default Agent limit?",
        description: (
          <>
            <span className="block">
              {reach(settings.budgetInheritingAgentCount, settings.budgetOverrideAgentCount, resulting)}
            </span>
            {stopped.length > 0 && (
              <span className="mt-1 block">
                {`${stopped.map((agent) => agent.agentName).join(", ")} ${stopped.length === 1 ? "has" : "have"} already spent more than that ${periodLabel(budget?.window)} and will stop making model calls${renews}.`}
              </span>
            )}
          </>
        ),
        destructive: stopped.length > 0,
        confirmLabel: stopped.length > 0 ? "Lower default and stop Agents" : undefined,
      }}
    >
      {editing && canEdit ? (
        <div className="flex max-w-xl flex-col gap-3">
          <MoneyInput
            label="Default limit"
            value={value}
            onChange={setDraft}
            onBlur={() => setTouched(true)}
            placeholder={String(settings.effectiveDefaultAgentLlmBudgetUsd)}
            hint={
              zeroNotice(value, "Agents following the default") ??
              (organizationLimit != null
                ? `Up to your organization limit of ${formatUsd(organizationLimit)} ${per}. Clear the field to use the platform default.`
                : "We couldn't check your organization limit, so the default can't be changed right now.")
            }
            error={touched || draft !== null ? error_ : null}
          />
          {updateSettings.error && (
            <SettingsErrorText>
              {updateSettings.error instanceof Error ? updateSettings.error.message : "Save failed"}
            </SettingsErrorText>
          )}
        </div>
      ) : (
        <dl className="grid gap-x-8 gap-y-4 sm:grid-cols-2">
          <Fact label="Limit">
            {formatUsd(settings.effectiveDefaultAgentLlmBudgetUsd)} {per}
            {organizationLimit != null && (
              <span style={{ color: "var(--ink-3)" }}> · of your {formatUsd(organizationLimit)} organization limit</span>
            )}
          </Fact>
          <Fact label="Set by">{stored == null ? "Platform default" : "This organization"}</Fact>
          <Fact label="Following the default">{plural(settings.budgetInheritingAgentCount, "Agent", "Agents")}</Fact>
          <Fact label="With their own limit">{plural(settings.budgetOverrideAgentCount, "Agent", "Agents")}</Fact>
        </dl>
      )}
    </SettingsSection>
  );
}
