"use client";

import { useEffect } from "react";

import { useModels } from "../hooks/use-models";

interface ModelSelectProps {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  "aria-label"?: string;
}

export function ModelSelect({
  value,
  onChange,
  disabled,
  "aria-label": ariaLabel = "Model",
}: ModelSelectProps) {
  const { models, defaultModel } = useModels();

  // Default to the configured default model when nothing is selected (hire flow).
  useEffect(() => {
    if (!value && defaultModel) {
      onChange(defaultModel);
    }
  }, [value, defaultModel, onChange]);

  // Keep the current value selectable even if it falls outside the allowlist
  // (e.g. an existing agent on a model that's no longer offered).
  const options =
    value && !models.some((m) => m.value === value)
      ? [{ value, label: value }, ...models]
      : models;

  return (
    <select
      className="af-input"
      aria-label={ariaLabel}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
    >
      {options.map((m) => (
        <option key={m.value} value={m.value}>
          {m.label}
        </option>
      ))}
    </select>
  );
}
