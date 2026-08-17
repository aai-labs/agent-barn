import type { ReactNode } from "react";

import { formatDateTime } from "../format";
import type { EventDelivery } from "../schemas";
import { EventDeliveryDetailRow } from "./event-delivery-detail-row";

export function EventDeliveryDetail({ delivery }: { delivery: EventDelivery }) {
  const hasFailure = !!delivery.lastError || !!delivery.deadLetterReason;
  const organizationLabel = delivery.organizationId
    ? `${delivery.organizationName ?? "Unknown organization"} (${delivery.organizationId})`
    : "Platform";

  return (
    <div className="space-y-4 px-10 py-4" style={{ background: "var(--bg-soft)" }}>
      <Section title="Delivery">
        <EventDeliveryDetailRow label="Delivery ID" value={delivery.id} mono />
        <EventDeliveryDetailRow label="Event ID" value={delivery.eventId} mono />
        <EventDeliveryDetailRow
          label="Event"
          value={`${delivery.eventName} · v${delivery.schemaVersion}`}
        />
        <EventDeliveryDetailRow label="Handler" value={delivery.handlerName} />
        <EventDeliveryDetailRow
          label="Organization"
          value={organizationLabel}
        />
        {delivery.actorDisplay && <EventDeliveryDetailRow label="Actor" value={delivery.actorDisplay} />}
        {delivery.subjectDisplay && <EventDeliveryDetailRow label="Subject" value={delivery.subjectDisplay} />}
        <EventDeliveryDetailRow label="Attempt count" value={delivery.attemptCount} />
      </Section>

      <Section title="Timeline">
        <EventDeliveryDetailRow label="Created at" value={formatDateTime(delivery.createdAt)} />
        <EventDeliveryDetailRow label="Enqueued at" value={formatDateTime(delivery.enqueuedAt)} />
        <EventDeliveryDetailRow label="Claimed at" value={formatDateTime(delivery.claimedAt)} />
        <EventDeliveryDetailRow label="Completed at" value={formatDateTime(delivery.completedAt)} />
        <EventDeliveryDetailRow
          label="Status since"
          value={delivery.statusSince ? formatDateTime(delivery.statusSince) : "Unknown"}
        />
        <EventDeliveryDetailRow label="Observed at" value={formatDateTime(delivery.observedAt)} />
      </Section>

      {hasFailure && (
        <Section title="Failure">
          {delivery.deadLetterReason && (
            <EventDeliveryDetailRow label="Dead-letter reason" value={delivery.deadLetterReason} />
          )}
          {delivery.lastError && <EventDeliveryDetailRow label="Last error" value={delivery.lastError} />}
        </Section>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h3
        className="mb-2 text-xs font-semibold uppercase tracking-wide"
        style={{ color: "var(--ink-4)" }}
      >
        {title}
      </h3>
      <div className="divide-y rounded-lg" style={{ border: "1px solid var(--line)", background: "var(--bg)" }}>
        {children}
      </div>
    </section>
  );
}
