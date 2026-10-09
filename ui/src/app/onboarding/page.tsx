import { Metadata } from "next";

import { OnboardingFlow } from "@/features/onboarding/components/onboarding-flow";

export const metadata: Metadata = { title: "Get started | Agent Barn" };

export default function OnboardingPage() {
  return <OnboardingFlow />;
}
