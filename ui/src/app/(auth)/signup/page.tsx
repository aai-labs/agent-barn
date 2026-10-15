import { Metadata } from "next";

import { LoginForm } from "@/auth/components/login-form";

export const metadata: Metadata = { title: "Sign up | Agent Barn" };

export default async function SignupPage({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const { error } = await searchParams;
  return <LoginForm signInError={error} origin="signup" />;
}
