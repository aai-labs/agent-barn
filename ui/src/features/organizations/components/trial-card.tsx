"use client";

import { useId, useState } from "react";

import { ConfirmationDialog } from "@/components/confirmation-dialog";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { MoneyInput } from "@/features/spend-limits/components/money-input";
import { getErrorDisplay } from "@/shared/api/error/get-error-display";

import { useEndTrial } from "../hooks/use-end-trial";
import type { PlatformOrganization } from "../schemas";
import { amountError, DEFAULT_SPEND_LIMIT_WINDOW, parseAmount, SPEND_LIMIT_WINDOWS } from "../spend-limit";

/** A trial organization, and the Platform Administrator's way to make it an ordinary one. */
export function TrialCard({ organization }: { organization: PlatformOrganization }) {
  const [confirming, setConfirming] = useState(false);
  const [amount, setAmount] = useState("");
  const [duration, setDuration] = useState<string>(DEFAULT_SPEND_LIMIT_WINDOW);
  const periodLabelId = useId();
  const endTrial = useEndTrial(organization.id);
  if (!organization.isTrial) return null;

  const error = amountError(amount, { required: true });
  const parsed = parseAmount(amount);

  return (
    <section className="af-card mb-9 p-5" aria-label="Trial">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <h2 className="m-0 text-[15px] font-semibold" style={{ color: "var(--ink)" }}>
            Free trial
          </h2>
          <p className="mb-0 mt-1 text-[13.5px] leading-relaxed" style={{ color: "var(--ink-3)" }}>
            This organization signed itself up. It runs a limited number of agents, set on the platform settings
            page, and its spend limit is granted once rather than renewing.
          </p>
        </div>
        <button
          type="button"
          className="af-btn"
          onClick={() => {
            setAmount(organization.llmBudgetUsd == null ? "" : String(organization.llmBudgetUsd));
            setDuration(DEFAULT_SPEND_LIMIT_WINDOW);
            endTrial.reset();
            setConfirming(true);
          }}
        >
          End trial
        </button>
      </div>
      <ConfirmationDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={`End the trial for ${organization.name}?`}
        description="It can then hire as many agents as any organization, and its owner can create organizations. Choose the spend limit it goes on to."
        confirmLabel="End trial"
        pendingLabel="Ending…"
        isPending={endTrial.isPending}
        confirmDisabled={!!error}
        onConfirm={async () => {
          if (parsed === null || Number.isNaN(parsed)) return;
          try {
            await endTrial.mutateAsync({ budgetUsd: parsed, budgetDuration: duration });
            setConfirming(false);
          } catch {
            /* The error stays in the dialog. */
          }
        }}
      >
        <div className="flex flex-wrap items-end gap-3">
          <MoneyInput label="New spend limit" value={amount} onChange={setAmount} error={error} />
          <div className="flex flex-col gap-1.5">
            <span id={periodLabelId} className="text-[0.84rem] font-medium" style={{ color: "var(--ink)" }}>
              Renewal period
            </span>
            <Select value={duration} onValueChange={setDuration}>
              <SelectTrigger className="af-input !h-auto" style={{ width: 160 }} aria-labelledby={periodLabelId}>
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
        </div>
        {endTrial.isError && (
          <p className="mb-0 mt-3 text-[13px]" role="alert" style={{ color: "var(--err)" }}>
            {getErrorDisplay(endTrial.error).description}
          </p>
        )}
      </ConfirmationDialog>
    </section>
  );
}
