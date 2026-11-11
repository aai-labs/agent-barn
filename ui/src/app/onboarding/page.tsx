import { Suspense } from "react";
import { Metadata } from "next";

import { OnboardingFlow } from "@/features/onboarding/components/onboarding-flow";

export const metadata: Metadata = { title: "Get started | Agent Barn" };

export default function OnboardingPage() {
  // The flow reads the tier picked on the pricing page from the address.
  return (
    <Suspense>
      <OnboardingFlow />
    </Suspense>
  );
}
