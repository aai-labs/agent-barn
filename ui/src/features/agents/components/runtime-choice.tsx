"use client";

type Runtime = "hermes" | "openclaw";

export function RuntimeChoice({ value, onChange, disabled = false }: {
  value: Runtime;
  onChange: (runtime: Runtime) => void;
  disabled?: boolean;
}) {
  return (
    <div role="radiogroup" aria-label="Runtime" className="flex rounded-full border p-[3px]" style={{ background: "var(--bg-soft)", borderColor: "var(--line)" }}>
      {(["hermes", "openclaw"] as const).map((runtime) => (
        <button
          key={runtime}
          type="button"
          role="radio"
          aria-checked={value === runtime}
          data-runtime={runtime}
          tabIndex={value === runtime ? 0 : -1}
          disabled={disabled}
          className="flex-1 rounded-full px-2.5 py-[7px] text-[13px] disabled:cursor-not-allowed disabled:opacity-60"
          style={value === runtime
            ? { background: "var(--bg-elev)", color: "var(--ink)", fontWeight: 600, boxShadow: "var(--shadow)" }
            : { color: "var(--ink-3)" }}
          onClick={() => onChange(runtime)}
          onKeyDown={(event) => {
            if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) return;
            event.preventDefault();
            const next = runtime === "hermes" ? "openclaw" : "hermes";
            onChange(next);
            event.currentTarget.parentElement?.querySelector<HTMLButtonElement>(`[data-runtime="${next}"]`)?.focus();
          }}
        >
          {runtime === "hermes" ? "Hermes" : "OpenClaw"}
        </button>
      ))}
    </div>
  );
}
