"use client";

import { useState } from "react";
import { Pencil } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { ConfirmationDialog } from "@/components/confirmation-dialog";
import { formatUsd } from "@/features/organizations/spend-limit";
import { getErrorDisplay } from "@/shared/api/error/get-error-display";

import { useBillingSettings } from "../hooks/use-billing-settings";
import { chargeUsd } from "../pricing";

type Draft = { min: string; max: string; rate: string; fee: string };

// The API's bounds: Stripe's smallest card payment, and caps that only stop a typo.
const MIN_PURCHASE_FLOOR_USD = 0.5;
const MAX_PURCHASE_CAP_USD = 100_000;
const MAX_CREDIT_RATE = 100;

function parseWithin(raw: string, { above, from, to }: { above?: number; from?: number; to: number }): number | null {
  const trimmed = raw.trim();
  const parsed = Number(trimmed);
  if (trimmed === "" || !Number.isFinite(parsed) || parsed > to) return null;
  if (above !== undefined && parsed <= above) return null;
  if (from !== undefined && parsed < from) return null;
  return parsed;
}

function Field({
  id,
  label,
  value,
  invalid,
  error,
  help,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  invalid: boolean;
  error: string;
  help: string;
  onChange: (value: string) => void;
}) {
  return (
    <div>
      <label className="mb-2 block text-sm font-medium" htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        inputMode="decimal"
        className="af-input max-w-[12rem]"
        value={value}
        aria-invalid={invalid}
        onChange={(event) => onChange(event.target.value)}
      />
      {invalid && (
        <p className="mt-2 text-sm" style={{ color: "var(--err)" }}>
          {error}
        </p>
      )}
      <p className="mb-0 mt-2 text-sm" style={{ color: "var(--ink-3)" }}>
        {help}
      </p>
    </div>
  );
}

function Saved({ label, children }: { label: string; children: string }) {
  return (
    <div>
      <dt className="mb-2 text-[0.7rem] font-semibold uppercase tracking-[0.08em]" style={{ color: "var(--ink-4)" }}>
        {label}
      </dt>
      <dd className="m-0 text-[0.9rem]">{children}</dd>
    </div>
  );
}

/** The Billing section of the platform settings page: how organizations buy credit. */
export function PlatformBillingSettings() {
  const { billingSettings, isLoading, error, reload, saveSettings, isSaving, saveError, resetSave } =
    useBillingSettings();
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saved, setSaved] = useState(false);
  const [confirming, setConfirming] = useState(false);

  if (isLoading) return <p className="m-0">Loading billing settings…</p>;
  if (error || !billingSettings)
    return <AppErrorState error={error} title="Could not load billing settings" onRetry={() => void reload()} />;

  const min = draft === null ? null : parseWithin(draft.min, { from: MIN_PURCHASE_FLOOR_USD, to: MAX_PURCHASE_CAP_USD });
  const max = draft === null ? null : parseWithin(draft.max, { from: MIN_PURCHASE_FLOOR_USD, to: MAX_PURCHASE_CAP_USD });
  const rate = draft === null ? null : parseWithin(draft.rate, { above: 0, to: MAX_CREDIT_RATE });
  const fee = draft === null ? null : parseWithin(draft.fee, { from: 0, to: 100 });
  const minInvalid = draft !== null && min === null;
  const maxInvalid = draft !== null && (max === null || (min !== null && max < min));
  const rateInvalid = draft !== null && rate === null;
  const feeInvalid = draft !== null && fee === null;

  function change(next: Partial<Draft>) {
    setDraft((current) => (current ? { ...current, ...next } : current));
    setSaved(false);
    resetSave();
  }

  // What a buyer pays for $1.00 of credit; below $1.00 the platform sells at a loss.
  const pricePerCredit = rate === null || fee === null ? null : (1 / rate) * (1 + fee / 100);

  async function submit() {
    if (min === null || max === null || rate === null || fee === null || max < min) return;
    try {
      await saveSettings({ minPurchaseUsd: min, maxPurchaseUsd: max, creditRate: rate, purchaseFeePercent: fee });
      setDraft(null);
      setSaved(true);
    } catch {
      /* The error stays beside the fields. */
    } finally {
      setConfirming(false);
    }
  }

  return (
    <section className="af-card overflow-hidden" aria-label="Billing settings">
      <div className="p-5">
        {!billingSettings.paymentsEnabled && (
          <p className="mb-4 mt-0 text-sm" style={{ color: "var(--ink-2)" }}>
            This deployment doesn&apos;t take payments. These settings apply once it does.
          </p>
        )}
        {draft !== null ? (
          <div className="flex flex-col gap-5">
            <Field
              id="billing-min"
              label="Smallest purchase"
              value={draft.min}
              invalid={minInvalid}
              error="Enter an amount from $0.50 to $100,000.00."
              help="The least credit an organization can buy at once, in US dollars."
              onChange={(value) => change({ min: value })}
            />
            <Field
              id="billing-max"
              label="Largest purchase"
              value={draft.max}
              invalid={maxInvalid}
              error="Enter an amount from the smallest purchase to $100,000.00."
              help="The most credit an organization can buy at once, in US dollars."
              onChange={(value) => change({ max: value })}
            />
            <Field
              id="billing-rate"
              label="Credit per dollar"
              value={draft.rate}
              invalid={rateInvalid}
              error="Enter a number above 0, up to 100."
              help="1 sells credit at cost. Below 1 keeps a margin on every purchase."
              onChange={(value) => change({ rate: value })}
            />
            <Field
              id="billing-fee"
              label="Purchase fee"
              value={draft.fee}
              invalid={feeInvalid}
              error="Enter a percentage from 0 to 100."
              help="A percentage added to every purchase, for example to cover card fees."
              onChange={(value) => change({ fee: value })}
            />
          </div>
        ) : (
          <dl className="m-0 grid gap-x-8 gap-y-5 sm:grid-cols-2">
            <Saved label="Smallest purchase">{formatUsd(billingSettings.minPurchaseUsd, 2)}</Saved>
            <Saved label="Largest purchase">{formatUsd(billingSettings.maxPurchaseUsd, 2)}</Saved>
            <Saved label="Credit per dollar">{String(billingSettings.creditRate)}</Saved>
            <Saved label="Purchase fee">{`${billingSettings.purchaseFeePercent}%`}</Saved>
          </dl>
        )}
        {saveError && (
          <p className="mt-3 text-sm" role="alert" style={{ color: "var(--err)" }}>
            {getErrorDisplay(saveError).description}
          </p>
        )}
        {saved && (
          <p className="mb-0 mt-3 text-sm" role="status">
            Billing settings saved.
          </p>
        )}
      </div>
      <footer className="flex flex-wrap justify-end gap-2 border-t px-5 py-3" style={{ borderColor: "var(--line)" }}>
        {draft !== null ? (
          <>
            <button
              className="af-btn"
              disabled={isSaving}
              onClick={() => {
                setDraft(null);
                resetSave();
              }}
            >
              Cancel
            </button>
            <button
              className="af-btn af-btn-primary"
              disabled={minInvalid || maxInvalid || rateInvalid || feeInvalid || isSaving}
              onClick={() => setConfirming(true)}
            >
              {isSaving ? "Saving…" : "Save"}
            </button>
          </>
        ) : (
          <button
            className="af-btn"
            onClick={() => {
              setDraft({
                min: String(billingSettings.minPurchaseUsd),
                max: String(billingSettings.maxPurchaseUsd),
                rate: String(billingSettings.creditRate),
                fee: String(billingSettings.purchaseFeePercent),
              });
              setSaved(false);
            }}
          >
            <Pencil size={14} /> Edit
          </button>
        )}
      </footer>
      {rate !== null && fee !== null && pricePerCredit !== null && (
        <ConfirmationDialog
          open={confirming}
          onOpenChange={setConfirming}
          title="Save billing settings?"
          description="They apply to every purchase from now on."
          confirmLabel="Save settings"
          pendingLabel="Saving…"
          isPending={isSaving}
          onConfirm={submit}
        >
          {pricePerCredit < 1 ? (
            <p className="m-0 text-[0.88rem]" role="alert" style={{ color: "var(--err)" }}>
              Each $1.00 of credit will cost buyers {formatUsd(chargeUsd(1, { creditRate: rate, purchaseFeePercent: fee }), 2)},
              less than it costs to provide. Every purchase will lose money.
            </p>
          ) : (
            <p className="m-0 text-[0.88rem]" style={{ color: "var(--ink-2)" }}>
              Each $1.00 of credit will cost buyers{" "}
              {formatUsd(chargeUsd(1, { creditRate: rate, purchaseFeePercent: fee }), 2)}.
            </p>
          )}
        </ConfirmationDialog>
      )}
    </section>
  );
}
