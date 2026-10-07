"use client";

import { useState } from "react";
import { SlidersHorizontal } from "lucide-react";

import { Badge } from "@/components/badge";
import { ConfirmationDialog } from "@/components/confirmation-dialog";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";

import { MAX_HOURLY_RATE_USD, MAX_OUTCOME_MINUTES } from "../constants";
import { useValueSettings } from "../hooks/use-value-settings";
import { useUpdateValueSettings } from "../hooks/use-update-value-settings";
import type { ValueSettings, ValueSettingsUpdate } from "../schemas";
import { outcomeTypeLabel } from "../utils";
import { RetryButton } from "./kpi-tiles";

const RATE_PATTERN = /^\d+(\.\d{1,2})?$/;
const MINUTES_PATTERN = /^\d+$/;
const RATE_ERROR = "Enter an amount from 0 to 10,000 with at most two decimals.";
const MINUTES_ERROR = "Enter whole minutes from 1 to 1,440.";
const SKELETON_ROWS = 6;

type Draft = {
  rate: string;
  overrides: Record<string, string | null>;
};

function draftFrom(settings: ValueSettings): Draft {
  return {
    rate: settings.hourlyRateUsd === null ? "" : String(settings.hourlyRateUsd),
    overrides: Object.fromEntries(
      settings.outcomeMinutes.map((row) => [
        row.outcomeType,
        row.overrideMinutes === null ? null : String(row.overrideMinutes),
      ]),
    ),
  };
}

function isDirty(draft: Draft, original: Draft): boolean {
  if (draft.rate.trim() !== original.rate) return true;
  return Object.keys(original.overrides).some(
    (outcomeType) => draft.overrides[outcomeType] !== original.overrides[outcomeType],
  );
}

function changesFrom(draft: Draft, original: Draft): ValueSettingsUpdate {
  const update: ValueSettingsUpdate = {};
  const rate = draft.rate.trim();
  if (rate !== original.rate) {
    update.hourlyRateUsd = rate === "" ? null : Number(rate);
  }
  const outcomeMinutes: Record<string, number | null> = {};
  for (const [outcomeType, minutes] of Object.entries(draft.overrides)) {
    if (minutes === original.overrides[outcomeType]) continue;
    outcomeMinutes[outcomeType] = minutes === null ? null : Number(minutes.trim());
  }
  if (Object.keys(outcomeMinutes).length > 0) update.outcomeMinutes = outcomeMinutes;
  return update;
}

function rateError(rate: string): string | null {
  const trimmed = rate.trim();
  if (trimmed === "") return null;
  if (!RATE_PATTERN.test(trimmed) || Number(trimmed) > MAX_HOURLY_RATE_USD) return RATE_ERROR;
  return null;
}

function minutesError(minutes: string | null): string | null {
  if (minutes === null) return null;
  const trimmed = minutes.trim();
  if (!MINUTES_PATTERN.test(trimmed)) return MINUTES_ERROR;
  const value = Number(trimmed);
  if (value < 1 || value > MAX_OUTCOME_MINUTES) return MINUTES_ERROR;
  return null;
}

export function ValueSettingsDialog() {
  const [open, setOpen] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [confirmingDiscard, setConfirmingDiscard] = useState(false);

  const close = () => {
    setOpen(false);
    setDirty(false);
    setConfirmingDiscard(false);
  };

  const requestClose = () => {
    if (dirty) {
      setConfirmingDiscard(true);
      return;
    }
    close();
  };

  return (
    <>
      <Dialog open={open} onOpenChange={(next) => (next ? setOpen(true) : requestClose())}>
        <DialogTrigger asChild>
          <button type="button" className="af-btn flex-shrink-0">
            <SlidersHorizontal size={14} /> Value settings
          </button>
        </DialogTrigger>
        <DialogContent
          className="flex max-h-[85dvh] w-[calc(100%-2rem)] max-w-xl flex-col gap-0 overflow-hidden rounded-2xl p-0 sm:rounded-2xl"
          style={{ background: "var(--bg-elev)", borderColor: "var(--line)", boxShadow: "var(--shadow-pop)" }}
        >
          <DialogHeader className="shrink-0 gap-2 border-b px-6 py-5 pr-12" style={{ borderColor: "var(--line)" }}>
            <DialogTitle className="text-[20px] font-semibold tracking-tight">Value settings</DialogTitle>
            <DialogDescription className="text-[13px] leading-relaxed">
              Changes recalculate every figure on this page, including past periods.
            </DialogDescription>
          </DialogHeader>
          <SettingsBody onDirtyChange={setDirty} onCancel={requestClose} onSaved={close} />
        </DialogContent>
      </Dialog>

      <ConfirmationDialog
        open={confirmingDiscard}
        onOpenChange={(next) => {
          if (!next) setConfirmingDiscard(false);
        }}
        title="Discard unsaved changes?"
        description="Your edits to the hourly rate and minutes will be lost."
        confirmLabel="Discard"
        variant="destructive"
        onConfirm={close}
      />
    </>
  );
}

function SettingsBody({
  onDirtyChange,
  onCancel,
  onSaved,
}: {
  onDirtyChange: (dirty: boolean) => void;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const { settings, settingsError, refetchSettings } = useValueSettings();

  if (settingsError && !settings) {
    return <SettingsReadError onRetry={() => void refetchSettings()} />;
  }

  if (!settings) {
    return (
      <div className="overflow-y-auto p-6">
        {Array.from({ length: SKELETON_ROWS }).map((_, i) => (
          <Skeleton key={i} className="mb-3 h-9 w-full" />
        ))}
      </div>
    );
  }

  return (
    <>
      {settingsError && <SettingsReadError onRetry={() => void refetchSettings()} />}
      <SettingsForm
        settings={settings}
        onDirtyChange={onDirtyChange}
        onCancel={onCancel}
        onSaved={onSaved}
      />
    </>
  );
}

function SettingsReadError({ onRetry }: { onRetry: () => void }) {
  return (
    <p className="m-0 shrink-0 px-6 py-3 text-[13px] flex items-center gap-2" style={{ color: "var(--err)" }}>
      Unable to load value settings.
      <RetryButton onRetry={onRetry} />
    </p>
  );
}

function SettingsForm({
  settings,
  onDirtyChange,
  onCancel,
  onSaved,
}: {
  settings: ValueSettings;
  onDirtyChange: (dirty: boolean) => void;
  onCancel: () => void;
  onSaved: () => void;
}) {
  // Keep the editing baseline stable when the query refreshes in the background.
  const [initialSettings] = useState(() => settings);
  const [original] = useState(() => draftFrom(settings));
  const [draft, setDraft] = useState<Draft>(() => original);
  const { mutate: save, isPending: isSaving } = useUpdateValueSettings();

  const update = (next: Draft) => {
    setDraft(next);
    onDirtyChange(isDirty(next, original));
  };

  const setOverride = (outcomeType: string, minutes: string | null) =>
    update({ ...draft, overrides: { ...draft.overrides, [outcomeType]: minutes } });

  const currentRateError = rateError(draft.rate);
  const hasErrors =
    currentRateError !== null ||
    Object.values(draft.overrides).some((minutes) => minutesError(minutes) !== null);
  const dirty = isDirty(draft, original);

  return (
    <>
      <div className="min-h-0 overflow-y-auto px-6 py-5 flex flex-col gap-5">
        <div>
          <label
            htmlFor="value-settings-rate"
            className="block text-[13px] font-medium mb-1"
            style={{ color: "var(--ink-2)" }}
          >
            Hourly rate (USD)
          </label>
          <input
            id="value-settings-rate"
            type="text"
            inputMode="decimal"
            className="af-input"
            aria-invalid={currentRateError !== null}
            value={draft.rate}
            onChange={(event) => update({ ...draft, rate: event.target.value })}
          />
          <p className="m-0 mt-2 text-[12px] leading-relaxed" style={{ color: "var(--ink-4)" }}>
            The estimated cost of one hour of human work. Hours saved × this rate gives value.
            Leave empty to report hours without a dollar value.
          </p>
          {currentRateError && (
            <p className="text-[12.5px] mt-1 mb-0" style={{ color: "var(--err)" }}>
              {currentRateError}
            </p>
          )}
        </div>

        <div className="flex flex-col gap-3">
          <p className="m-0 text-[13px] font-medium" style={{ color: "var(--ink-2)" }}>
            Minutes saved per outcome
          </p>
          <p className="m-0 text-[12px] leading-relaxed" style={{ color: "var(--ink-4)" }}>
            Estimate the human work each successful action saves. These are assumptions you can
            adjust, rather than measured working time.
          </p>
          {initialSettings.outcomeMinutes.map((row) => {
            const label = outcomeTypeLabel(row.outcomeType);
            const override = draft.overrides[row.outcomeType];
            const error = minutesError(override);
            return (
              <div key={row.outcomeType} role="group" aria-label={label}>
                <div className="flex items-center gap-2">
                  <span className="flex-1 text-[13px]" style={{ color: "var(--ink-2)" }}>
                    {label}
                  </span>
                  {override === null ? (
                    <Badge>Default</Badge>
                  ) : (
                    <Badge variant="accent">Custom</Badge>
                  )}
                  <input
                    type="text"
                    inputMode="numeric"
                    className="af-input"
                    style={{ width: "5rem" }}
                    aria-label={`${label} minutes`}
                    aria-invalid={error !== null}
                    value={override ?? String(row.defaultMinutes)}
                    onChange={(event) => setOverride(row.outcomeType, event.target.value)}
                  />
                  <span className="text-[12px]" style={{ color: "var(--ink-4)" }}>
                    min
                  </span>
                </div>
                {override !== null && (
                  <button
                    type="button"
                    className="text-[12px] underline mt-1"
                    style={{ color: "var(--ink-3)" }}
                    onClick={() => setOverride(row.outcomeType, null)}
                  >
                    Reset to default ({row.defaultMinutes} min)
                  </button>
                )}
                {error && (
                  <p className="text-[12.5px] mt-1 mb-0" style={{ color: "var(--err)" }}>
                    {error}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      </div>

      <DialogFooter className="shrink-0 flex-row justify-end border-t px-6 py-4" style={{ borderColor: "var(--line)" }}>
        <button type="button" className="af-btn" onClick={onCancel}>
          Cancel
        </button>
        <button
          type="button"
          className="af-btn af-btn-primary"
          disabled={!dirty || hasErrors || isSaving}
          onClick={() => save(changesFrom(draft, original), { onSuccess: onSaved })}
        >
          {isSaving ? "Saving…" : "Save"}
        </button>
      </DialogFooter>
    </>
  );
}
