"use client";

import { type ReactNode, useEffect } from "react";

import { useLogout } from "@/auth/hooks/use-logout";

export default function AuthLayout({ children }: { children: ReactNode }) {
  const { logout } = useLogout();

  useEffect(() => {
    void logout();
  }, [logout]);

  return <>{children}</>;
}

