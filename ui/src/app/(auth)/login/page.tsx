import { LoginForm } from "@/auth/components/login-form";

export default function LoginPage() {
  return (
    <div
      className="flex min-h-svh flex-col items-center justify-center p-6"
      style={{ background: "var(--bg)" }}
    >
      <LoginForm />
    </div>
  );
}
