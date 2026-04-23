"use client";

import { type ReactNode, useEffect } from "react";
import { usePathname } from "next/navigation";

import { PUBLIC_PATHS } from "@/auth/constants";
import { SessionExpirationHandler } from "@/auth/providers/session-expiration-handler";
import { useAuthStore } from "@/auth/providers/auth-store";
import { UserContextProvider } from "@/auth/providers/user-context-provider";
import { OrganizationProvider } from "@/features/organizations/providers/organization-provider";
import { initStoreSync } from "@/features/organizations/stores/init-store-sync";

export function AppProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? "";
  const isSessionExpired = useAuthStore((state) => state.isSessionExpired);
  const isPublicPage = PUBLIC_PATHS.some(
    (path) => pathname === path || pathname.startsWith(`${path}/`),
  );

  useEffect(() => {
    initStoreSync();
  }, []);

  if (isPublicPage) {
    return <>{children}</>;
  }

  if (isSessionExpired) {
    return <SessionExpirationHandler />;
  }

  return (
    <UserContextProvider>
      <OrganizationProvider>{children}</OrganizationProvider>
    </UserContextProvider>
  );
}
