"use client";

import { useId } from "react";

/** Labelled workflow text field; shows its validation message once revealed. */
export function WorkflowField({
  label,
  value,
  onChange,
  onBlur,
  error,
  area = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  onBlur?: () => void;
  error?: string;
  area?: boolean;
}) {
  const errorId = useId();
  const control = {
    className: `af-input block w-full mt-2${area ? " min-h-24" : ""}`,
    value,
    onChange: (
      event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>,
    ) => onChange(event.target.value),
    onBlur,
    "aria-invalid": error ? true : undefined,
    "aria-describedby": error ? errorId : undefined,
    style: error ? { borderColor: "var(--err)" } : undefined,
  };
  return (
    <div className="mb-4">
      <label className="block text-sm font-medium">
        {label}
        {area ? (
          <textarea {...control} />
        ) : (
          <input {...control} />
        )}
      </label>
      {error && (
        <p
          id={errorId}
          className="mt-1.5 text-xs"
          style={{ color: "var(--err)" }}
        >
          {error}
        </p>
      )}
    </div>
  );
}
