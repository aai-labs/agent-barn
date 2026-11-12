"use client";

import { Plus, Trash2 } from "lucide-react";

import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { type WorkflowDraft } from "../schemas";
import { inputKeyFromLabel } from "../utils";
import { inputField } from "../validation";

type WorkflowInput = WorkflowDraft["inputs"][number];

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
  const text = (
    index: number,
    name: "label" | "description",
    label: string,
    placeholder: string,
    onValue: (value: string) => void,
  ) => {
    const error = errorFor(inputField(index, name));
    return (
      <div className="min-w-0 flex-1">
        <input
          className={`af-input block w-full${name === "label" ? " font-semibold" : ""}`}
          aria-label={label}
          aria-invalid={error ? true : undefined}
          placeholder={placeholder}
          value={inputs[index][name]}
          onChange={(event) => onValue(event.target.value)}
          onBlur={() => onTouch(inputField(index, name))}
          style={error ? { borderColor: "var(--err)" } : undefined}
        />
        {error && (
          <p className="mt-1.5 text-xs" style={{ color: "var(--err)" }}>
            {error}
          </p>
        )}
      </div>
    );
  };
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
            className="flex flex-wrap items-start gap-2 rounded-2xl border border-[var(--line)] bg-[var(--bg-elev)] p-3"
          >
            {/* Saved keys stay unchanged until their label is edited. */}
            {text(index, "label", `Input ${index + 1} label`, "e.g. Release tag", (label) =>
              update(index, { label, key: inputKeyFromLabel(label) }),
            )}
            {text(
              index,
              "description",
              `Input ${index + 1} description`,
              "What should the person starting a run enter?",
              (description) => update(index, { description }),
            )}
            <Select
              value={item.type}
              onValueChange={(type: WorkflowInput["type"]) => update(index, { type })}
            >
              <SelectTrigger aria-label={`Input ${index + 1} type`} className="w-28">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value="text">Text</SelectItem>
                  <SelectItem value="file">File</SelectItem>
                  <SelectItem value="number">Number</SelectItem>
                  <SelectItem value="boolean">Yes / no</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
            <label className="flex h-9 items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={item.required}
                onChange={(event) => update(index, { required: event.target.checked })}
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
