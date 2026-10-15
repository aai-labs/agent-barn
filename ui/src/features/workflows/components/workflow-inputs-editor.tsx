"use client";

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
import { WorkflowField } from "./workflow-field";

type WorkflowInput = WorkflowDraft["inputs"][number];

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
    <section className="af-card p-6">
      <h2 className="text-xl font-semibold mb-4">Required inputs</h2>
      <p className="text-sm mb-4" style={{ color: "var(--ink-3)" }}>
        Describe the information needed for a future run.
      </p>
      {inputs.map((item, index) => (
        <div
          key={index}
          className="border-b mb-4 pb-4"
          style={{ borderColor: "var(--line)" }}
        >
          <WorkflowField
            label={`Input ${index + 1} label`}
            value={item.label}
            // Saved keys stay unchanged until their label is edited.
            onChange={(label) =>
              update(index, { label, key: inputKeyFromLabel(label) })
            }
            onBlur={() => onTouch(inputField(index, "label"))}
            error={errorFor(inputField(index, "label"))}
          />
          <WorkflowField
            label={`Input ${index + 1} description`}
            value={item.description}
            onChange={(description) => update(index, { description })}
            onBlur={() => onTouch(inputField(index, "description"))}
            error={errorFor(inputField(index, "description"))}
            area
          />
          <Select
            value={item.type}
            onValueChange={(type: WorkflowInput["type"]) =>
              update(index, { type })
            }
          >
            <SelectTrigger aria-label={`Input ${index + 1} type`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectItem value="text">Text</SelectItem>
                <SelectItem value="number">Number</SelectItem>
                <SelectItem value="boolean">Yes / no</SelectItem>
              </SelectGroup>
            </SelectContent>
          </Select>
          <label className="flex gap-2 items-center my-3 text-sm">
            <input
              type="checkbox"
              checked={item.required}
              onChange={(e) => update(index, { required: e.target.checked })}
            />
            Required
          </label>
          <button
            className="af-btn af-btn-sm"
            onClick={() => onChange(inputs.filter((_, i) => i !== index))}
          >
            Remove input {index + 1}
          </button>
        </div>
      ))}
      <button
        className="af-btn"
        disabled={disabled || inputs.length >= 30}
        onClick={() =>
          onChange([
            ...inputs,
            {
              key: "",
              label: "",
              description: "",
              type: "text",
              required: true,
            },
          ])
        }
      >
        + Add an input
      </button>
    </section>
  );
}
