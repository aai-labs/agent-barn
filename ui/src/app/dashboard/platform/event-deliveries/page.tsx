import { PlatformAdminOnly } from "@/auth/components/platform-admin-only";
import { EventDeliveryMonitorPage } from "@/features/event-deliveries/components/event-delivery-monitor-page";

export default function PlatformEventDeliveriesPage() {
  return (
    <PlatformAdminOnly>
      <EventDeliveryMonitorPage />
    </PlatformAdminOnly>
  );
}
