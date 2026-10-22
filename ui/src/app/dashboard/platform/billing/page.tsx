import { PlatformAdminOnly } from "@/auth/components/platform-admin-only";
import { PlatformCreditHistory } from "@/features/billing/components/platform-credit-history";

export default function PlatformBillingPage() {
  return (
    <PlatformAdminOnly>
      <PlatformCreditHistory />
    </PlatformAdminOnly>
  );
}
