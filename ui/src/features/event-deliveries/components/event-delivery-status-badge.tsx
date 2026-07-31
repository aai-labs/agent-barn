import { EVENT_DELIVERY_STATUS_LABELS } from "../constants";
import type { EventDeliveryStatus } from "../schemas";

const STATUS_STYLE: Record<EventDeliveryStatus, { bg: string; fg: string }> = {
  PENDING: { bg: "var(--bg-soft)", fg: "var(--ink-3)" },
  ENQUEUED: { bg: "var(--bg-soft)", fg: "var(--ink-2)" },
  PROCESSING: { bg: "var(--warn-soft)", fg: "var(--warn)" },
  SUCCEEDED: { bg: "var(--ok-soft)", fg: "var(--ok)" },
  DEAD_LETTERED: { bg: "var(--err-soft)", fg: "var(--err)" },
};

export function EventDeliveryStatusBadge({ status }: { status: EventDeliveryStatus }) {
  const style = STATUS_STYLE[status];
  return (
    <span
      className="inline-flex items-center rounded-md px-2 py-0.5 text-[0.75rem] font-medium whitespace-nowrap"
      style={{ background: style.bg, color: style.fg }}
    >
      {EVENT_DELIVERY_STATUS_LABELS[status]}
    </span>
  );
}
