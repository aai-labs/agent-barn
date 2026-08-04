import { ChevronDown, ChevronRight } from "lucide-react";

import { formatAgeSeconds } from "../format";
import type { EventDelivery } from "../schemas";
import { EventDeliveryDetail } from "./event-delivery-detail";
import { EventDeliveryStatusBadge } from "./event-delivery-status-badge";

const ROW_GRID =
  "grid-cols-[28px_130px_minmax(160px,1.3fr)_minmax(140px,1fr)_minmax(140px,1fr)_90px_70px]";

export function EventDeliveryRow({
  delivery,
  expanded,
  onToggle,
}: {
  delivery: EventDelivery;
  expanded: boolean;
  onToggle: () => void;
}) {
  const ageSeconds = delivery.statusSince
    ? (Date.parse(delivery.observedAt) - Date.parse(delivery.statusSince)) / 1000
    : null;

  return (
    <div style={{ borderTop: "1px solid var(--line)" }}>
      <button
        type="button"
        onClick={onToggle}
        className={`grid ${ROW_GRID} w-full items-center px-3 py-2.5 text-left text-[0.8125rem] af-hover-bg`}
      >
        <span style={{ color: "var(--ink-4)" }}>
          {expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
        </span>
        <span>
          <EventDeliveryStatusBadge status={delivery.status} />
        </span>
        <span className="truncate" style={{ color: "var(--ink)" }}>
          {delivery.eventName}
          <span style={{ color: "var(--ink-4)" }}> · v{delivery.schemaVersion}</span>
        </span>
        <span className="truncate" style={{ color: "var(--ink-2)" }}>
          {delivery.organizationName ?? "Platform"}
        </span>
        <span className="truncate" style={{ color: "var(--ink-3)" }}>
          {delivery.handlerName}
        </span>
        <span style={{ color: "var(--ink-3)" }}>{formatAgeSeconds(ageSeconds)}</span>
        <span style={{ color: "var(--ink-3)" }}>{delivery.attemptCount}</span>
      </button>
      {expanded && <EventDeliveryDetail delivery={delivery} />}
    </div>
  );
}
