"use client";

import type { ReactNode } from "react";

/**
 * A quiet inline note above a settings section's content — for the one thing a
 * reader needs to know before they touch the controls, not for general help text.
 */
export function SettingsHint({ children }: { children: ReactNode }) {
  return (
    <div
      className="mb-5 flex items-start gap-2 rounded-xl px-3.5 py-3 text-[0.8rem] leading-[1.5]"
      style={{ background: "var(--bg-soft)", color: "var(--ink-3)" }}
    >
      {children}
    </div>
  );
}
