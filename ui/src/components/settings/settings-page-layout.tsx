"use client";

import type { ReactNode } from "react";

/**
 * The body of a settings surface: one mounted section, headed by its own name and
 * description. The navigation panel lists the sections. `min-w-0` is what stops a wide
 * table or code block from pushing the page sideways.
 */
export function SettingsPageLayout({
  heading,
  description,
  children,
}: {
  heading: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <div className="min-w-0">
      <div className="mb-4">
        <h2 className="m-0 text-[1.25rem] font-semibold" style={{ color: "var(--ink)" }}>
          {heading}
        </h2>
        <p className="mb-0 mt-1 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
          {description}
        </p>
      </div>

      {children}
    </div>
  );
}
