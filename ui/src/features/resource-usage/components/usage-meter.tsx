import { meterTone, type MeterTone } from "../utils";

const TONE_COLOR: Record<MeterTone, string> = {
  ok: "var(--ok)",
  warn: "var(--warn)",
  err: "var(--err)",
};

/**
 * How much of its limit a container is using.
 *
 * Draws nothing when there is no limit to compare against, rather than a bar that
 * looks empty and reads as "idle".
 */
export function UsageMeter({
  ratio,
  label,
  className,
}: {
  ratio: number | null;
  label: string;
  className?: string;
}) {
  const percent = ratio === null ? 0 : Math.min(Math.max(ratio, 0), 1) * 100;
  return (
    <div
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={ratio === null ? undefined : Math.round(percent)}
      className={`h-1.5 w-full overflow-hidden rounded-full ${className ?? ""}`}
      style={{ background: "var(--bg-soft)" }}
    >
      <div
        className="h-full rounded-full"
        style={{
          width: `${percent}%`,
          background: TONE_COLOR[meterTone(ratio)],
          transition: "width .2s",
        }}
      />
    </div>
  );
}
