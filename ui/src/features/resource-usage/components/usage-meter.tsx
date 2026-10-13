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
 * looks empty and reads as "idle". `markerRatio` puts a thin tick where the container's
 * request sits on the same scale, so the bar shows the use, the request and the limit.
 */
export function UsageMeter({
  ratio,
  label,
  className,
  markerRatio = null,
}: {
  ratio: number | null;
  label: string;
  className?: string;
  markerRatio?: number | null;
}) {
  const percent = ratio === null ? 0 : Math.min(Math.max(ratio, 0), 1) * 100;
  const markerPercent = markerRatio === null ? null : Math.min(Math.max(markerRatio, 0), 1) * 100;
  return (
    <div
      role="meter"
      aria-label={markerPercent === null ? label : `${label}, request at ${Math.round(markerPercent)}% of the limit`}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={ratio === null ? undefined : Math.round(percent)}
      className={`relative h-1.5 w-full overflow-hidden rounded-full ${className ?? ""}`}
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
      {markerPercent !== null && (
        <div
          className="absolute inset-y-0 w-0.5"
          // Centred on its position, and kept inside the bar at either end.
          style={{ left: `clamp(0px, calc(${markerPercent}% - 1px), calc(100% - 2px))`, background: "var(--ink)" }}
          data-testid="usage-meter-request-marker"
        />
      )}
    </div>
  );
}
