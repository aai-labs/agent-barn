import type { ReactNode } from "react";

export function EventDeliveryDetailRow({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="grid gap-2 px-3 py-1.5 text-xs md:grid-cols-[160px_minmax(0,1fr)]">
      <div className="font-medium" style={{ color: "var(--ink-3)" }}>
        {label}
      </div>
      <div className={mono ? "break-all font-mono text-xs" : "min-w-0"} style={{ color: "var(--ink)" }}>
        {value}
      </div>
    </div>
  );
}
