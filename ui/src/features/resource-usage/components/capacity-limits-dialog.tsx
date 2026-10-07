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

/** A limit as the text box shows it: whole when it is whole, else up to three decimals. */
function toText(value: number | null): string {
  return value === null ? "" : String(Number(value.toFixed(3)));
}

/** Blank clears the limit (null). Anything else must be a number above zero. */
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
  const [memory, setMemory] = useState(() =>
    toText(capacity.memoryLimitBytes === null ? null : capacity.memoryLimitBytes / BYTES_PER_GIB),
  );
  const [cpu, setCpu] = useState(() => toText(capacity.cpuLimitCores));
  const [showErrors, setShowErrors] = useState(false);
  const update = useUpdateResourceLimits();

  const parsedMemory = parseLimit(memory);
  const parsedCpu = parseLimit(cpu);

  function save() {
    setShowErrors(true);
    if (parsedMemory.invalid || parsedCpu.invalid) return;
    update.mutate(
      {
        memoryLimitBytes: parsedMemory.value === null ? null : Math.round(parsedMemory.value * BYTES_PER_GIB),
        cpuLimitCores: parsedCpu.value,
      },
      { onSuccess: () => onOpenChange(false) },
    );
  }

  const failure = update.error instanceof Error ? update.error.message : null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md" data-testid="capacity-limits-dialog">
        <DialogHeader>
          <DialogTitle>Capacity limits</DialogTitle>
          <DialogDescription>
            Enter the namespace ResourceQuota values for <code>limits.memory</code> and{" "}
            <code>limits.cpu</code>, the Hard column of <code>kubectl describe quota</code>. We can&apos;t
            read them ourselves, so the page compares what you enter with what the namespace has
            committed. Leave a field blank for no limit.
          </DialogDescription>
        </DialogHeader>

        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            save();
          }}
        >
          <div className="flex flex-col gap-1.5">
            <label
              className="text-[0.8rem] font-medium"
              style={{ color: "var(--ink-2)" }}
              htmlFor="capacity-memory"
            >
              Memory (GiB)
            </label>
            <input
              id="capacity-memory"
              type="text"
              inputMode="decimal"
              className="af-input w-full"
              value={memory}
              onChange={(event) => setMemory(event.target.value)}
              placeholder="e.g. 70"
              autoComplete="off"
              aria-invalid={showErrors && parsedMemory.invalid}
            />
            {showErrors && parsedMemory.invalid && (
              <p className="m-0 text-[0.78rem]" style={{ color: "var(--err)" }} role="alert">
                Enter a number above 0, or leave it blank.
              </p>
            )}
          </div>

          <div className="flex flex-col gap-1.5">
            <label
              className="text-[0.8rem] font-medium"
              style={{ color: "var(--ink-2)" }}
              htmlFor="capacity-cpu"
            >
              CPU (cores)
            </label>
            <input
              id="capacity-cpu"
              type="text"
              inputMode="decimal"
              className="af-input w-full"
              value={cpu}
              onChange={(event) => setCpu(event.target.value)}
              placeholder="e.g. 24"
              autoComplete="off"
              aria-invalid={showErrors && parsedCpu.invalid}
            />
            {showErrors && parsedCpu.invalid && (
              <p className="m-0 text-[0.78rem]" style={{ color: "var(--err)" }} role="alert">
                Enter a number above 0, or leave it blank.
              </p>
            )}
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

          {capacity.limitsUpdatedAt && (
            <p className="m-0 text-[0.78rem]" style={{ color: "var(--ink-4)" }}>
              Last changed {formatChanged(capacity.limitsUpdatedAt)}
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
