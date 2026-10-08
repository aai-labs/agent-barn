import type { MeterTone } from "../utils";

const TONE_COLOR: Record<MeterTone, string> = {
  ok: "var(--ink)",
  warn: "var(--warn)",
  err: "var(--err)",
};

/**
 * A stat that can turn amber or red. The Costs tab's card has no tone, and its figures
 * have no limit to be close to; these do.
 */
export function UsageStatCard({
  label,
  value,
  hint,
  tone = "ok",
  testId,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: MeterTone;
  testId?: string;
}) {
  return (
    <div className="af-card px-4 py-3.5" data-testid={testId} data-tone={tone}>
      <p className="m-0 mb-1 text-[12px]" style={{ color: "var(--ink-4)" }}>
        {label}
      </p>
      <p
        className="m-0 truncate text-[20px] font-semibold"
        style={{ color: TONE_COLOR[tone] }}
        title={value}
      >
        {value}
      </p>
      {hint && (
        <p className="m-0 mt-0.5 text-[12px]" style={{ color: "var(--ink-4)" }}>
          {hint}
        </p>
      )}
    </div>
  );
}
