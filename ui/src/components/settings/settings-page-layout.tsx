"use client";

import type { ReactNode } from "react";

/**
 * The two-column body of a settings surface: the sidebar rail beside one mounted
 * section, headed by the section's own name and description.
 *
 * The `14rem` track must stay equal to the sidebar's `lg:w-56`, and `minmax(0,1fr)`
 * is what stops a wide table or code block in the content column from pushing the
 * page sideways.
 */
export function SettingsPageLayout({
  sidebar,
  heading,
  description,
  children,
}: {
  sidebar: ReactNode;
  heading: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <div className="grid gap-8 lg:grid-cols-[14rem_minmax(0,1fr)] lg:items-start">
      {sidebar}

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
    </div>
  );
}
