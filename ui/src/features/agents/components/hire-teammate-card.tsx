import { Plus } from "lucide-react";

export function HireTeammateCard({ onHire }: { onHire: () => void }) {
  return (
    <button
      type="button"
      onClick={onHire}
      aria-label="Hire a teammate"
      className="af-card af-card-hover flex min-h-56 cursor-pointer flex-col items-center justify-center gap-4 p-6 text-center focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--accent-color)]"
      style={{ borderStyle: "dashed", background: "transparent" }}
    >
      <span className="flex size-11 items-center justify-center rounded-full border bg-white" style={{ borderColor: "var(--line)", color: "var(--ink)" }}>
        <Plus className="size-4" aria-hidden="true" />
      </span>
      <span className="flex max-w-56 flex-col gap-1">
        <span className="text-[0.9375rem] font-semibold" style={{ color: "var(--ink-3)" }}>Hire a teammate</span>
        <span className="text-[0.844rem] leading-relaxed" style={{ color: "var(--ink-4)" }}>
          A scrum master, PR reviewer, support rep — ready in a couple of minutes.
        </span>
      </span>
    </button>
  );
}
