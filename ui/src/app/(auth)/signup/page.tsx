import { Metadata } from "next";

import { SignInStep } from "@/features/onboarding/components/sign-in-step";

export const metadata: Metadata = { title: "Sign in | Agent Barn" };

export default async function SignupPage({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const { error } = await searchParams;
  return <SignInStep error={error} />;
}
