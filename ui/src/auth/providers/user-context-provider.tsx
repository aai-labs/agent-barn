"use client";

import { createContext, type ReactNode, useContext, useEffect } from "react";
import { useRouter } from "next/navigation";
import type { QueryObserverResult } from "@tanstack/react-query";

import { AuthLoadingFallback } from "@/auth/components/auth-loading-fallback";
import { AppErrorState } from "@/components/app-error-state";
import { ApiResult } from "@/shared/api/types";

import type { CurrentUserContext } from "../schemas";
import { useCurrentUserContext } from "../hooks/use-current-user-context";
import { useAuthStore } from "./auth-store";

type UserContextType = {
  userContext: CurrentUserContext;
  user: CurrentUserContext;
  refetch: () => Promise<QueryObserverResult<ApiResult<CurrentUserContext>, Error>>;
};

const CurrentUserContextState = createContext<UserContextType | undefined>(
  undefined,
);

export function UserContextProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const clearToken = useAuthStore((state) => state.clearToken);
  const { data, isPending, isError, error, refetch } = useCurrentUserContext();
  const userContext = data?.data ?? null;

  const status = (error as { status?: number } | null)?.status ?? null;
  const shouldRedirectToLogin = status === 401;

  useEffect(() => {
    if (shouldRedirectToLogin) {
      clearToken();
      router.replace("/login");
    }
  }, [clearToken, router, shouldRedirectToLogin]);

  if (isPending) {
    return <AuthLoadingFallback message="Loading your account..." />;
  }

  if (shouldRedirectToLogin) {
    return <AuthLoadingFallback message="Redirecting to login..." />;
  }

  if (isError || !userContext) {
    return (
      <AppErrorState
        error={error}
        title="We couldn't load your account"
        description="Your session is valid, but we couldn't load the account context."
        onRetry={() => {
          void refetch();
        }}
        retryLabel="Retry account"
        className="min-h-svh"
      />
    );
  }

  return (
    <CurrentUserContextState.Provider
      value={{
        userContext,
        user: userContext,
        refetch,
      }}
    >
      {children}
    </CurrentUserContextState.Provider>
  );
}

export function useCurrentUser() {
  const context = useContext(CurrentUserContextState);
  if (!context) {
    throw new Error("useCurrentUser must be used inside UserContextProvider");
  }
  return context;
}
