import Link from "next/link";

import { GoogleSignInButton, SignInError } from "./google-sign-in";
import { OnboardingShell, StepHeading } from "./onboarding-shell";

/** Step 1: sign in, or sign up, with Google. */
export function SignInStep({ error }: { error?: string | null }) {
  return (
    <OnboardingShell step={1}>
      <StepHeading title="Sign in to Agent Barn">New here? Signing in creates your account.</StepHeading>
      <div className="flex flex-col gap-4">
        <SignInError code={error} />
        <GoogleSignInButton origin="signup" />
        <p className="m-0 text-center text-[12.5px]" style={{ color: "var(--ink-4)" }}>
          By continuing you agree to the{" "}
          <Link href="#" style={{ color: "var(--ink-3)" }}>
            Terms
          </Link>{" "}
          and{" "}
          <Link href="#" style={{ color: "var(--ink-3)" }}>
            Privacy Policy
          </Link>
          .
        </p>
        <p className="m-0 text-center text-[12.5px]" style={{ color: "var(--ink-3)" }}>
          Have a password?{" "}
          <Link href="/login" style={{ color: "var(--accent-ink)" }}>
            Log in
          </Link>
        </p>
      </div>
    </OnboardingShell>
  );
}
