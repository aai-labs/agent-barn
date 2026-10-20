"use client";

import type { ReactNode } from "react";

/**
 * The body of a settings surface: one mounted section, headed by its own name and
 * description. The navigation panel lists the sections and the path bar names where you
 * are, so the section's name is the page's heading. `min-w-0` is what stops a wide table
 * or code block from pushing the page sideways.
 */
export function SettingsPageLayout({
  heading,
  description,
  aside,
  children,
}: {
  heading: string;
  description: string;
  /** Beside the heading, e.g. the viewer's access level. */
  aside?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="min-w-0">
      <div className="mb-6 flex flex-wrap items-start gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1">
          <h1 className="m-0 text-[1.75rem] font-semibold tracking-[-0.02em]" style={{ color: "var(--ink)" }}>
            {heading}
          </h1>
          <p className="mb-0 mt-1 text-[0.9rem]" style={{ color: "var(--ink-3)" }}>
            {description}
          </p>
        </div>
        {aside}
      </div>

      {children}
    </div>
  );
}
