"use client";

import { useSharedCredentialBriefs } from "../hooks/use-shared-credential-briefs";
import type { SharedCredentialBrief } from "../schemas";

interface SharedCredentialPickerProps {
  provider: string;
  value: string | undefined;
  onChange: (brief: SharedCredentialBrief | null) => void;
}

export function SharedCredentialPicker({
  provider,
  value,
  onChange,
}: SharedCredentialPickerProps) {
  const { briefs, isLoading } = useSharedCredentialBriefs();
  const filtered = briefs.filter((b) => b.provider === provider);

  if (isLoading) {
    return (
      <div className="text-[0.8125rem]" style={{ color: "var(--ink-3)" }}>
        Loading shared credentials…
      </div>
    );
  }

  if (filtered.length === 0) {
    return (
      <div className="text-[0.8125rem]" style={{ color: "var(--ink-4)" }}>
        No shared credentials available for this provider.
      </div>
    );
  }

  return (
    <select
      className="af-select"
      value={value ?? ""}
      onChange={(e) => {
        const id = e.target.value;
        if (!id) {
          onChange(null);
          return;
        }
        const brief = filtered.find((b) => b.id === id) ?? null;
        onChange(brief);
      }}
    >
      <option value="">Select a shared credential…</option>
      {filtered.map((b) => (
        <option key={b.id} value={b.id}>
          {b.name}
        </option>
      ))}
    </select>
  );
}
