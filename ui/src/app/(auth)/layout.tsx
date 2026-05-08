"use client";

import { type ReactNode, useEffect } from "react";

import { AuthLoadingFallback } from "@/auth/components/auth-loading-fallback";
import { useLogout } from "@/auth/hooks/use-logout";

export default function AuthLayout({ children }: { children: ReactNode }) {
  const { logout, isLoggingOut } = useLogout();

  useEffect(() => {
    void logout();
  }, [logout]);

  if (isLoggingOut) {
    return <AuthLoadingFallback message="Preparing authentication..." />;
  }

  return <>{children}</>;
}

