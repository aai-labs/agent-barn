import type { EventDeliveryStatus } from "./schemas";

export const EVENT_DELIVERY_STATUS_LABELS: Record<EventDeliveryStatus, string> = {
  PENDING: "Pending",
  ENQUEUED: "Enqueued",
  PROCESSING: "Processing",
  SUCCEEDED: "Succeeded",
  DEAD_LETTERED: "Dead-lettered",
};
