import { Suspense } from "react";
import { Metadata } from "next";

import { BillingPage } from "@/features/billing/components/billing-page";

export const metadata: Metadata = {
  title: "Billing | Agent Barn",
};

export default function OrganizationBillingPage() {
  // The page reads ?checkout= to say how a payment went.
  return (
    <Suspense>
      <BillingPage />
    </Suspense>
  );
}
