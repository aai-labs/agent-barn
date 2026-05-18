import { SignupForm } from "@/auth/components/signup-form";

export default function SignupPage() {
  return (
    <div
      className="flex min-h-svh flex-col items-center justify-center p-6"
      style={{ background: "var(--bg)" }}
    >
      <SignupForm />
    </div>
  );
}
