"use client";

import { useId } from "react";

import { useModels } from "../hooks/use-models";
import { formatModelName } from "../utils";
import { ModelSelect } from "./model-select";

/**
 * Picking between following the organization's default model and pinning a specific
 * one. `null` means follow the default.
 *
 * This is deliberately an explicit two-state control rather than a combobox that
 * pre-fills the default: pre-filling is indistinguishable from a user choosing that
 * model, which is how every Agent ended up pinned to whatever the default happened to
 * be on the day it was created.
 */
export function ModelChoice({
  value,
  effectiveDefaultModel,
  onChange,
  disabled,
}: {
  value: string | null;
  effectiveDefaultModel: string;
  onChange: (value: string | null) => void;
  disabled?: boolean;
}) {
  const { models } = useModels();
  const usingDefault = !value;
  // The picker labels models "GLM 5.2"; naming the same model "z-ai/glm-5.2" here
  // would read as a different thing. Fall back to the slug for a model the
  // catalogue no longer carries.
  const defaultLabel =
    models.find((model) => model.value === effectiveDefaultModel)?.label ??
    formatModelName(effectiveDefaultModel);
  // Scoped per instance so two of these on one page cannot share a radio group.
  const groupName = useId();

  return (
    <div className="flex flex-col gap-2.5">
      <label className="flex items-start gap-2.5 text-[0.84rem]" style={{ color: "var(--ink)" }}>
        <input
          type="radio"
          name={groupName}
          className="mt-0.5"
          style={{ accentColor: "var(--ink)" }}
          checked={usingDefault}
          disabled={disabled}
          onChange={() => onChange(null)}
        />
        <span className="flex flex-col">
          <span className="font-medium">Use organization default</span>
          <span className="text-[0.78rem]" style={{ color: "var(--ink-3)" }}>
            {defaultLabel || "—"}
          </span>
        </span>
      </label>

      <label className="flex items-start gap-2.5 text-[0.84rem]" style={{ color: "var(--ink)" }}>
        <input
          type="radio"
          name={groupName}
          className="mt-0.5"
          style={{ accentColor: "var(--ink)" }}
          checked={!usingDefault}
          disabled={disabled}
          // Seed the picker with the default so switching to "specific" starts from
          // something real instead of an empty control.
          onChange={() => onChange(value || effectiveDefaultModel)}
        />
        <span className="font-medium">Choose a specific model</span>
      </label>

      {!usingDefault && (
        <div className="pl-[1.7rem]">
          <ModelSelect
            value={value ?? ""}
            onChange={onChange}
            disabled={disabled}
            aria-label="Model"
          />
        </div>
      )}
    </div>
  );
}
