import type { ReactNode } from "react";

export function DetailStatTile({
  icon,
  label,
  children,
}: {
  icon: ReactNode;
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="af-card px-4 py-3.5">
      <div
        className="text-[11px] font-semibold uppercase tracking-[0.06em] mb-1.5"
        style={{ color: "var(--ink-5)" }}
      >
        {label}
      </div>
      <div
        className="flex items-center gap-2 text-[13.5px] min-w-0"
        style={{ color: "var(--ink)" }}
      >
        <span style={{ color: "var(--ink-4)", flexShrink: 0 }}>{icon}</span>
        <span className="min-w-0 truncate">{children}</span>
      </div>
    </div>
  );
}
