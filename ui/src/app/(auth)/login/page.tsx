import { LoginForm } from "@/auth/components/login-form";

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const { error } = await searchParams;
  return <LoginForm signInError={error} origin="login" />;
}
