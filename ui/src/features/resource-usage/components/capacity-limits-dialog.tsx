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
import type { ResourceLimits, ResourceLimitsUpdate } from "../schemas";

const BYTES_PER_GIB = 1024 ** 3;
const NUMBER_PATTERN = /^\d+(\.\d+)?$/;
const WHOLE_PATTERN = /^\d+$/;

export type CeilingKey = keyof ResourceLimitsUpdate;

interface Field {
  key: CeilingKey;
  /** Named as the quota names it, so it reads the same as `kubectl describe quota`. */
  label: string;
  placeholder: string;
  /** How the box shows the stored figure: GiB for bytes, or the number as it is. */
  unit: "gib" | "cores" | "count";
}

const FIELDS: Record<CeilingKey, Field> = {
  limitsMemoryBytes: { key: "limitsMemoryBytes", label: "limits.memory (GiB)", placeholder: "e.g. 50", unit: "gib" },
  limitsCpuCores: { key: "limitsCpuCores", label: "limits.cpu (cores)", placeholder: "e.g. 30", unit: "cores" },
  requestsMemoryBytes: {
    key: "requestsMemoryBytes",
    label: "requests.memory (GiB)",
    placeholder: "e.g. 20",
    unit: "gib",
  },
  requestsCpuCores: { key: "requestsCpuCores", label: "requests.cpu (cores)", placeholder: "e.g. 5", unit: "cores" },
  requestsStorageBytes: {
    key: "requestsStorageBytes",
    label: "requests.storage (GiB)",
    placeholder: "e.g. 30",
    unit: "gib",
  },
  pods: { key: "pods", label: "pods", placeholder: "e.g. 50", unit: "count" },
};

/** The four lines the Platform Resource Usage page compares with what pods commit. */
export const CPU_AND_MEMORY_CEILINGS: CeilingKey[] = [
  "limitsMemoryBytes",
  "limitsCpuCores",
  "requestsMemoryBytes",
  "requestsCpuCores",
];

/** Every line, storage and pods first, since those are what stop a new agent first. */
export const ALL_CEILINGS: CeilingKey[] = ["requestsStorageBytes", "pods", ...CPU_AND_MEMORY_CEILINGS];

/** A ceiling as the text box shows it: whole when it is whole, else up to three decimals. */
function toText(value: number | null | undefined, unit: Field["unit"]): string {
  if (value === null || value === undefined) return "";
  const shown = unit === "gib" ? value / BYTES_PER_GIB : value;
  return String(Number(shown.toFixed(3)));
}

/** Blank clears the ceiling (null). Anything else must be a number above zero, and a count a whole one. */
function parseLimit(text: string, unit: Field["unit"]): { value: number | null; invalid: boolean } {
  const trimmed = text.trim();
  if (trimmed === "") return { value: null, invalid: false };
  const pattern = unit === "count" ? WHOLE_PATTERN : NUMBER_PATTERN;
  const value = pattern.test(trimmed) ? Number(trimmed) : Number.NaN;
  return value > 0 ? { value, invalid: false } : { value: null, invalid: true };
}

/** What the API stores: whole bytes for GiB, the number itself otherwise. */
function toStored(value: number | null, unit: Field["unit"]): number | null {
  if (value === null) return null;
  return unit === "gib" ? Math.round(value * BYTES_PER_GIB) : value;
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

interface CapacityLimitsDialogProps {
  /** What is saved; the boxes start from it. */
  ceilings: Partial<ResourceLimits>;
  /** The quota lines to offer. Only these are sent, so the others stay as they are. */
  fields?: CeilingKey[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Where a Platform Administrator types in the namespace's ResourceQuota ceilings.
 *
 * They are typed in because the quota cannot be read with the access we have. Shown in GiB,
 * cores and pods, the way `kubectl describe quota` prints them, and sent as whole bytes.
 */
export function CapacityLimitsDialog({
  ceilings,
  fields: keys = CPU_AND_MEMORY_CEILINGS,
  open,
  onOpenChange,
}: CapacityLimitsDialogProps) {
  const fields = keys.map((key) => FIELDS[key]);
  // Keyed on `open` by the parent, so each opening starts from what is saved.
  const [values, setValues] = useState<Partial<Record<CeilingKey, string>>>(() =>
    Object.fromEntries(fields.map((field) => [field.key, toText(ceilings[field.key], field.unit)])),
  );
  const [showErrors, setShowErrors] = useState(false);
  const update = useUpdateResourceLimits();

  const parsed = Object.fromEntries(
    fields.map((field) => [field.key, parseLimit(values[field.key] ?? "", field.unit)]),
  ) as Record<CeilingKey, ReturnType<typeof parseLimit>>;
  const anyInvalid = fields.some((field) => parsed[field.key].invalid);

  function save() {
    setShowErrors(true);
    if (anyInvalid) return;
    const body: ResourceLimitsUpdate = Object.fromEntries(
      fields.map((field) => [field.key, toStored(parsed[field.key].value, field.unit)]),
    );
    update.mutate(body, { onSuccess: () => onOpenChange(false) });
  }

  const failure = update.error instanceof Error ? update.error.message : null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md" data-testid="capacity-limits-dialog">
        <DialogHeader>
          <DialogTitle>Namespace quota</DialogTitle>
          <DialogDescription>
            Enter the namespace ResourceQuota values, the Hard column of{" "}
            <code>kubectl describe quota</code>. Anything new is refused when any one line would go
            over, so enter every line the quota has. We can&apos;t read them ourselves, so the page
            compares what you enter with what the namespace has committed. Leave a field blank for no
            quota.
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
            {fields.map((field) => (
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
                  inputMode={field.unit === "count" ? "numeric" : "decimal"}
                  className="af-input w-full"
                  value={values[field.key] ?? ""}
                  onChange={(event) => setValues((current) => ({ ...current, [field.key]: event.target.value }))}
                  placeholder={field.placeholder}
                  autoComplete="off"
                  aria-invalid={showErrors && parsed[field.key].invalid}
                />
                {showErrors && parsed[field.key].invalid && (
                  <p className="m-0 text-[0.78rem]" style={{ color: "var(--err)" }} role="alert">
                    {field.unit === "count"
                      ? "Enter a whole number above 0, or leave it blank."
                      : "Enter a number above 0, or leave it blank."}
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

          {ceilings.updatedAt && (
            <p className="m-0 text-[0.78rem]" style={{ color: "var(--ink-4)" }}>
              Last changed {formatChanged(ceilings.updatedAt)}
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
