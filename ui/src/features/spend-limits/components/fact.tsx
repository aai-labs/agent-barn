import type { ReactNode } from "react";

/** One labelled figure in a spend-limit card, matching the Agent defaults fact grid. */
export function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt
        className="text-[0.72rem] font-semibold uppercase tracking-[0.08em]"
        style={{ color: "var(--ink-4)" }}
      >
        {label}
      </dt>
      <dd className="mb-0 mt-1 text-[0.9rem]" style={{ color: "var(--ink-2)" }}>
        {children}
      </dd>
    </div>
  );
}
