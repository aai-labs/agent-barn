import { LoginForm } from "@/auth/components/login-form";

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const { error } = await searchParams;
  return (
    <div
      className="flex min-h-svh flex-col items-center justify-center p-6"
      style={{ background: "var(--bg)" }}
    >
      <LoginForm signInError={error} />
    </div>
  );
}
