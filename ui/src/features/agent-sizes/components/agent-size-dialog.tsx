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

import { useAgentSizeActions } from "../hooks/use-agent-sizes";
import type { AgentSize, AgentSizeValues } from "../schemas";
import { GIB, MAX_CPU_MILLICORES, MAX_MEMORY_BYTES, MAX_STORAGE_BYTES, MIB, MIN_STORAGE_BYTES } from "../utils";

const DECIMAL = /^\d+(\.\d{1,3})?$/;
const WHOLE = /^\d+$/;

type FieldKey = "name" | "cpuRequest" | "cpuLimit" | "memoryRequest" | "memoryLimit" | "storage";

/** Bytes in a unit, exact to three places, so a value the API took in bytes is not shown rounded. */
function inUnit(bytes: number, unit: number): string {
  return String(Number((bytes / unit).toFixed(3)));
}

function textOf(size: AgentSize | null): Record<FieldKey, string> {
  if (!size) return { name: "", cpuRequest: "", cpuLimit: "", memoryRequest: "", memoryLimit: "", storage: "1" };
  return {
    name: size.name,
    cpuRequest: String(size.cpuRequestMillicores / 1000),
    cpuLimit: String(size.cpuLimitMillicores / 1000),
    memoryRequest: inUnit(size.memoryRequestBytes, MIB),
    memoryLimit: inUnit(size.memoryLimitBytes, MIB),
    storage: inUnit(size.storageBytes, GIB),
  };
}

/**
 * The values the text describes, or why they can't be used, per field.
 *
 * A field left as it was keeps the saved value exactly: the form shows it in MiB or GiB, and
 * reading that back would round a value set in bytes through the API, so saving a renamed size
 * could quietly grow every volume on it.
 */
function parse(
  text: Record<FieldKey, string>,
  size: AgentSize | null,
): { values: AgentSizeValues | null; errors: Partial<Record<FieldKey, string>> } {
  const errors: Partial<Record<FieldKey, string>> = {};
  const saved = size ? textOf(size) : null;
  const unchanged = (key: FieldKey) => saved !== null && text[key] === saved[key];
  const cpu = (key: FieldKey) => {
    const value = text[key].trim();
    const millicores = DECIMAL.test(value) ? Math.round(Number(value) * 1000) : Number.NaN;
    if (!(millicores > 0) || millicores > MAX_CPU_MILLICORES) {
      errors[key] = `Enter a number of vCPU above 0 and up to ${MAX_CPU_MILLICORES / 1000}.`;
    }
    return millicores;
  };
  const memory = (key: "memoryRequest" | "memoryLimit") => {
    if (size && unchanged(key)) return key === "memoryRequest" ? size.memoryRequestBytes : size.memoryLimitBytes;
    const value = text[key].trim();
    const bytes = WHOLE.test(value) ? Number(value) * MIB : Number.NaN;
    if (!(bytes > 0) || bytes > MAX_MEMORY_BYTES) {
      errors[key] = `Enter whole MiB above 0 and up to ${MAX_MEMORY_BYTES / MIB}.`;
    }
    return bytes;
  };

  const storage = () => {
    if (size && unchanged("storage")) return size.storageBytes;
    const value = text.storage.trim();
    const bytes = WHOLE.test(value) ? Number(value) * GIB : Number.NaN;
    if (!(bytes >= MIN_STORAGE_BYTES) || bytes > MAX_STORAGE_BYTES) {
      errors.storage = `Enter whole GiB from ${MIN_STORAGE_BYTES / GIB} to ${MAX_STORAGE_BYTES / GIB}.`;
    }
    return bytes;
  };

  const name = text.name.trim();
  if (!name) errors.name = "Give the size a name.";
  const values = {
    name,
    cpuRequestMillicores: cpu("cpuRequest"),
    cpuLimitMillicores: cpu("cpuLimit"),
    memoryRequestBytes: memory("memoryRequest"),
    memoryLimitBytes: memory("memoryLimit"),
    storageBytes: storage(),
  };
  if (!errors.cpuRequest && !errors.cpuLimit && values.cpuRequestMillicores > values.cpuLimitMillicores) {
    errors.cpuRequest = "The request can't be more than the limit.";
  }
  if (!errors.memoryRequest && !errors.memoryLimit && values.memoryRequestBytes > values.memoryLimitBytes) {
    errors.memoryRequest = "The request can't be more than the limit.";
  }
  return { values: Object.keys(errors).length ? null : values, errors };
}

const FIELDS: { key: Exclude<FieldKey, "name">; label: string; placeholder: string; inputMode: "decimal" | "numeric" }[] = [
  { key: "cpuRequest", label: "CPU request (vCPU)", placeholder: "e.g. 0.25", inputMode: "decimal" },
  { key: "cpuLimit", label: "CPU limit (vCPU)", placeholder: "e.g. 1", inputMode: "decimal" },
  { key: "memoryRequest", label: "Memory request (MiB)", placeholder: "e.g. 512", inputMode: "numeric" },
  { key: "memoryLimit", label: "Memory limit (MiB)", placeholder: "e.g. 2048", inputMode: "numeric" },
  { key: "storage", label: "Storage (GiB)", placeholder: "e.g. 10", inputMode: "numeric" },
];

/**
 * Add a size to the catalog, or edit one. The request is what the namespace quota charges and
 * the scheduler reserves; the limit is how far the Agent may grow before it is throttled
 * (CPU) or stopped for using too much memory.
 */
export function AgentSizeDialog({
  size,
  open,
  onOpenChange,
}: {
  /** The size to edit, or null to add one. */
  size: AgentSize | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  // Keyed on each opening by the parent, so the form starts from what is saved.
  const [text, setText] = useState(() => textOf(size));
  const [showErrors, setShowErrors] = useState(false);
  const { create, update } = useAgentSizeActions();
  const mutation = size ? update : create;
  const { values, errors } = parse(text, size);

  function save() {
    setShowErrors(true);
    if (!values) return;
    const done = { onSuccess: () => onOpenChange(false) };
    if (size) update.mutate({ id: size.id, data: values }, done);
    else create.mutate(values, done);
  }

  const failure = mutation.error instanceof Error ? mutation.error.message : null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md" data-testid="agent-size-dialog">
        <DialogHeader>
          <DialogTitle>{size ? `Edit ${size.name}` : "Add a size"}</DialogTitle>
          <DialogDescription>
            The request is what the namespace quota charges and the cluster reserves for the Agent; the limit is how far
            it may grow. Storage is the Agent&apos;s volume, which grows to it but never shrinks. A change reaches each Agent
            on this size the next time it starts.
          </DialogDescription>
        </DialogHeader>

        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            save();
          }}
        >
          <Field id="agent-size-name" label="Name" error={showErrors ? errors.name : undefined}>
            <input
              id="agent-size-name"
              type="text"
              className="af-input w-full"
              value={text.name}
              maxLength={64}
              onChange={(event) => setText((current) => ({ ...current, name: event.target.value }))}
              placeholder="e.g. Large"
              autoComplete="off"
              aria-invalid={showErrors && !!errors.name}
            />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            {FIELDS.map((field) => (
              <Field
                key={field.key}
                id={`agent-size-${field.key}`}
                label={field.label}
                error={showErrors ? errors[field.key] : undefined}
              >
                <input
                  id={`agent-size-${field.key}`}
                  type="text"
                  inputMode={field.inputMode}
                  className="af-input w-full"
                  value={text[field.key]}
                  onChange={(event) => setText((current) => ({ ...current, [field.key]: event.target.value }))}
                  placeholder={field.placeholder}
                  autoComplete="off"
                  aria-invalid={showErrors && !!errors[field.key]}
                />
              </Field>
            ))}
          </div>

          {failure && (
            <p className="m-0 text-[0.8rem]" style={{ color: "var(--err)" }} role="alert" data-testid="agent-size-error">
              {failure}
            </p>
          )}

          <DialogFooter>
            <button type="button" className="af-btn" onClick={() => onOpenChange(false)}>
              Cancel
            </button>
            <button type="submit" className="af-btn af-btn-primary" disabled={mutation.isPending}>
              {mutation.isPending && <Loader2 size={14} className="animate-spin" />} {size ? "Save" : "Add size"}
            </button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function Field({ id, label, error, children }: { id: string; label: string; error?: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-[0.8rem] font-medium" style={{ color: "var(--ink-2)" }} htmlFor={id}>
        {label}
      </label>
      {children}
      {error && (
        <p className="m-0 text-[0.78rem]" style={{ color: "var(--err)" }} role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
