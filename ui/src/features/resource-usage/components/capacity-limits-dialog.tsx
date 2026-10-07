"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

import { useUpdateResourceLimits } from "../hooks/use-update-resource-limits";
import type { PlatformCapacity } from "../schemas";

const BYTES_PER_GIB = 1024 ** 3;
const NUMBER_PATTERN = /^\d+(\.\d+)?$/;

type FieldKey = "limitsMemory" | "limitsCpu" | "requestsMemory" | "requestsCpu";

interface Field {
  key: FieldKey;
  /** Named as the quota names it, so it reads the same as `kubectl describe quota`. */
  label: string;
  placeholder: string;
}

const FIELDS: Field[] = [
  { key: "limitsMemory", label: "limits.memory (GiB)", placeholder: "e.g. 52.5" },
  { key: "limitsCpu", label: "limits.cpu (cores)", placeholder: "e.g. 30" },
  { key: "requestsMemory", label: "requests.memory (GiB)", placeholder: "e.g. 20" },
  { key: "requestsCpu", label: "requests.cpu (cores)", placeholder: "e.g. 5" },
];

/** A ceiling as the text box shows it: whole when it is whole, else up to three decimals. */
function toText(value: number | null): string {
  return value === null ? "" : String(Number(value.toFixed(3)));
}

/** Blank clears the ceiling (null). Anything else must be a number above zero. */
function parseLimit(text: string): { value: number | null; invalid: boolean } {
  const trimmed = text.trim();
  if (trimmed === "") return { value: null, invalid: false };
  const value = NUMBER_PATTERN.test(trimmed) ? Number(trimmed) : Number.NaN;
  return value > 0 ? { value, invalid: false } : { value: null, invalid: true };
}

function formatChanged(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function savedText(capacity: PlatformCapacity): Record<FieldKey, string> {
  const gib = (bytes: number | null) => (bytes === null ? null : bytes / BYTES_PER_GIB);
  return {
    limitsMemory: toText(gib(capacity.limitsMemoryBytes)),
    limitsCpu: toText(capacity.limitsCpuCores),
    requestsMemory: toText(gib(capacity.requestsMemoryBytes)),
    requestsCpu: toText(capacity.requestsCpuCores),
  };
}

interface CapacityLimitsDialogProps {
  capacity: PlatformCapacity;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Where a Platform Administrator types in the namespace's ResourceQuota ceilings.
 *
 * They are typed in because the quota cannot be read with the access we have. Shown in GiB
 * and cores, the way `kubectl describe quota` prints them, and sent as whole bytes.
 */
export function CapacityLimitsDialog({ capacity, open, onOpenChange }: CapacityLimitsDialogProps) {
  // Keyed on `open` by the parent, so each opening starts from what is saved.
  const [values, setValues] = useState(() => savedText(capacity));
  const [showErrors, setShowErrors] = useState(false);
  const update = useUpdateResourceLimits();

  const parsed = Object.fromEntries(FIELDS.map((field) => [field.key, parseLimit(values[field.key])])) as Record<
    FieldKey,
    ReturnType<typeof parseLimit>
  >;
  const anyInvalid = FIELDS.some((field) => parsed[field.key].invalid);

  function save() {
    setShowErrors(true);
    if (anyInvalid) return;
    const bytes = (value: number | null) => (value === null ? null : Math.round(value * BYTES_PER_GIB));
    update.mutate(
      {
        limitsMemoryBytes: bytes(parsed.limitsMemory.value),
        limitsCpuCores: parsed.limitsCpu.value,
        requestsMemoryBytes: bytes(parsed.requestsMemory.value),
        requestsCpuCores: parsed.requestsCpu.value,
      },
      { onSuccess: () => onOpenChange(false) },
    );
  }

  const failure = update.error instanceof Error ? update.error.message : null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md" data-testid="capacity-limits-dialog">
        <DialogHeader>
          <DialogTitle>Namespace quota</DialogTitle>
          <DialogDescription>
            Enter the namespace ResourceQuota values, the Hard column of{" "}
            <code>kubectl describe quota</code>. A new pod is refused when any one of the four would go
            over, so enter all of them. We can&apos;t read them ourselves, so the page compares what you
            enter with what the namespace has committed. Leave a field blank for no quota.
          </DialogDescription>
        </DialogHeader>

        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            save();
          }}
        >
          <div className="grid gap-4 sm:grid-cols-2">
            {FIELDS.map((field) => (
              <div key={field.key} className="flex flex-col gap-1.5">
                <label
                  className="text-[0.8rem] font-medium"
                  style={{ color: "var(--ink-2)" }}
                  htmlFor={`capacity-input-${field.key}`}
                >
                  {field.label}
                </label>
                <input
                  id={`capacity-input-${field.key}`}
                  type="text"
                  inputMode="decimal"
                  className="af-input w-full"
                  value={values[field.key]}
                  onChange={(event) => setValues((current) => ({ ...current, [field.key]: event.target.value }))}
                  placeholder={field.placeholder}
                  autoComplete="off"
                  aria-invalid={showErrors && parsed[field.key].invalid}
                />
                {showErrors && parsed[field.key].invalid && (
                  <p className="m-0 text-[0.78rem]" style={{ color: "var(--err)" }} role="alert">
                    Enter a number above 0, or leave it blank.
                  </p>
                )}
              </div>
            ))}
          </div>

          {failure && (
            <p
              className="m-0 text-[0.8rem]"
              style={{ color: "var(--err)" }}
              role="alert"
              data-testid="capacity-limits-error"
            >
              {failure}
            </p>
          )}

          {capacity.ceilingsUpdatedAt && (
            <p className="m-0 text-[0.78rem]" style={{ color: "var(--ink-4)" }}>
              Last changed {formatChanged(capacity.ceilingsUpdatedAt)}
            </p>
          )}

          <DialogFooter>
            <button type="button" className="af-btn" onClick={() => onOpenChange(false)}>
              Cancel
            </button>
            <button
              type="submit"
              className="af-btn af-btn-primary"
              disabled={update.isPending}
              data-testid="capacity-limits-save"
            >
              {update.isPending && <Loader2 size={14} className="animate-spin" />} Save
            </button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
