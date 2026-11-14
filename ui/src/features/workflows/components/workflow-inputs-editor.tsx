"use client";

import { Plus, Trash2 } from "lucide-react";

import { Checkbox } from "@/components/ui/checkbox";

import { type WorkflowDraft } from "../schemas";
import {
  inputKeyFromLabel,
  inputLabelFromDescription,
  onRadioGroupKeyDown,
} from "../utils";
import { inputField } from "../validation";

type WorkflowInput = WorkflowDraft["inputs"][number];

const TYPES: { value: WorkflowInput["type"]; label: string }[] = [
  { value: "text", label: "Text" },
  { value: "file", label: "File" },
  { value: "number", label: "Number" },
  { value: "boolean", label: "Yes / no" },
];

/** The information a run asks for when it starts, one row per input. */
export function WorkflowInputsEditor({
  inputs,
  onChange,
  disabled,
  errorFor,
  onTouch,
}: {
  inputs: WorkflowInput[];
  onChange: (inputs: WorkflowInput[]) => void;
  disabled: boolean;
  errorFor: (field: string) => string | undefined;
  onTouch: (field: string) => void;
}) {
  const update = (index: number, patch: Partial<WorkflowInput>) =>
    onChange(
      inputs.map((input, i) => (i === index ? { ...input, ...patch } : input)),
    );
  return (
    <section aria-label="Inputs">
      <div className="mb-2 flex items-baseline justify-between">
        <h3 className="text-sm font-semibold">
          Inputs{" "}
          <span className="font-normal text-[var(--ink-3)]">
            (asked when a run starts)
          </span>
        </h3>
        <span className="text-xs text-[var(--ink-3)]">
          {inputs.length} {inputs.length === 1 ? "input" : "inputs"}
        </span>
      </div>
      <ul className="space-y-2.5">
        {inputs.map((item, index) => (
          <li
            key={index}
            aria-label={`Input ${index + 1}`}
            className="rounded-2xl border border-[var(--line)] bg-[var(--bg-elev)]"
          >
            <div className="p-4">
              <InputDescription
                index={index}
                value={item.description}
                error={errorFor(inputField(index, "description"))}
                onBlur={() => onTouch(inputField(index, "description"))}
                // Its first line becomes the label on the start-run form and the key
                // behind it; saved labels and keys stay until it is edited.
                onChange={(description) => {
                  const label = inputLabelFromDescription(description);
                  update(index, { description, label, key: inputKeyFromLabel(label) });
                }}
              />
            </div>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-[var(--line)] px-4 py-2.5">
              <div
                role="radiogroup"
                aria-label={`Input ${index + 1} type`}
                className="inline-flex rounded-lg bg-[var(--bg-soft)] p-0.5"
                onKeyDown={onRadioGroupKeyDown}
              >
                {TYPES.map((type) => {
                  const selected = item.type === type.value;
                  return (
                    <button
                      key={type.value}
                      type="button"
                      role="radio"
                      aria-checked={selected}
                      tabIndex={selected ? 0 : -1}
                      onClick={() => update(index, { type: type.value })}
                      className={`h-7 rounded-md px-3 text-xs font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--accent-color)] ${
                        selected
                          ? "bg-[var(--bg-elev)] text-[var(--ink)] shadow-sm"
                          : "text-[var(--ink-3)] hover:text-[var(--ink)]"
                      }`}
                    >
                      {type.label}
                    </button>
                  );
                })}
              </div>
              <label className="ml-auto flex items-center gap-2 text-sm text-[var(--ink-2)]">
                <Checkbox
                  checked={item.required}
                  onCheckedChange={(checked) =>
                    update(index, { required: checked === true })
                  }
                  aria-label={`Input ${index + 1} required`}
                />
                Required
              </label>
              <button
                type="button"
                className="af-btn af-btn-icon af-btn-sm"
                aria-label={`Remove input ${index + 1}`}
                onClick={() => onChange(inputs.filter((_, i) => i !== index))}
              >
                <Trash2 size={15} />
              </button>
            </div>
          </li>
        ))}
      </ul>
      <button
        type="button"
        className="af-btn af-btn-sm mt-3"
        disabled={disabled || inputs.length >= 30}
        onClick={() =>
          onChange([
            ...inputs,
            { key: "", label: "", description: "", type: "text", required: true },
          ])
        }
      >
        <Plus size={14} /> Add input
      </button>
    </section>
  );
}

function InputDescription({
  index,
  value,
  error,
  onChange,
  onBlur,
}: {
  index: number;
  value: string;
  error?: string;
  onChange: (value: string) => void;
  onBlur: () => void;
}) {
  const errorId = `workflow-input-${index}-description-error`;
  return (
    <div className="min-w-0">
      <input
        className="af-input block w-full"
        aria-label={`Input ${index + 1} description`}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? errorId : undefined}
        placeholder="What should the person starting a run enter? e.g. Release tag"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onBlur={onBlur}
        style={error ? { borderColor: "var(--err)" } : undefined}
      />
      {error && (
        <p id={errorId} className="mt-1.5 text-xs" style={{ color: "var(--err)" }}>
          {error}
        </p>
      )}
    </div>
  );
}
