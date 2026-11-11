import { Metadata } from "next";

import { LoginForm } from "@/auth/components/login-form";

export const metadata: Metadata = { title: "Sign up | Agent Barn" };

export default async function SignupPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string; tier?: string }>;
}) {
  const { error, tier } = await searchParams;
  // The tier chosen on the pricing page, carried through Google to onboarding.
  return <LoginForm signInError={error} origin="signup" tierKey={tier} />;
}
