"use client";

import { type ReactNode, useId } from "react";

/**
 * The one amount field every spend-limit surface uses: a visible label, a "$" prefix,
 * and its hint and error tied to the input so assistive tech reads them with it.
 * Showing the error is the caller's decision, so it can wait until the field is
 * touched rather than scolding an empty field the moment it appears.
 */
export function MoneyInput({
  label,
  value,
  onChange,
  onBlur,
  hint,
  error,
  disabled,
  placeholder,
  describedBy: extraDescribedBy,
  action,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  onBlur?: () => void;
  hint?: string;
  error?: string | null;
  disabled?: boolean;
  placeholder?: string;
  /** Ids of text elsewhere on the card that also describes this amount. */
  describedBy?: string;
  /** Rendered beside the field, e.g. a way back to the inherited amount. */
  action?: ReactNode;
}) {
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const describedBy =
    [hint ? hintId : null, error ? errorId : null, extraDescribedBy].filter(Boolean).join(" ") || undefined;

  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-[0.84rem] font-medium" style={{ color: "var(--ink)" }}>
        {label}
        {/* The "$" prefix is decorative, so the currency is said in the name instead. */}
        <span className="sr-only"> (US dollars)</span>
      </label>
      {/* af-input in globals.css is unlayered, so its padding and width beat Tailwind
          utilities; inline styles are what actually apply. */}
      <div className="flex flex-wrap items-center gap-3">
      <div className="relative" style={{ width: 180 }}>
        <span
          aria-hidden
          className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[13px]"
          style={{ color: "var(--ink-4)" }}
        >
          $
        </span>
        <input
          id={id}
          className="af-input"
          style={{ paddingLeft: 26 }}
          inputMode="decimal"
          value={value}
          placeholder={placeholder}
          disabled={disabled}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          onChange={(event) => onChange(event.target.value)}
          onBlur={onBlur}
        />
      </div>
      {action}
      </div>
      {hint && (
        <p id={hintId} className="m-0 text-[0.8rem]" style={{ color: "var(--ink-3)" }}>
          {hint}
        </p>
      )}
      {error && (
        <p id={errorId} className="m-0 text-xs" style={{ color: "var(--err)" }}>
          {error}
        </p>
      )}
    </div>
  );
}
