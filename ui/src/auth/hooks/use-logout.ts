"use client";

import { useCallback, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { api, ORGANIZATION_HEADER } from "@/shared/api";

import { useAuthStore } from "../providers/auth-store";

export function useLogout() {
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const { setToken } = useAuthStore();
  const queryClient = useQueryClient();

  const logout = useCallback(async () => {
    setIsLoggingOut(true);
    try {
      await api.post("/api/v1/auth/logout", undefined, { skipAuth: true });
    } catch {
      // Best-effort logout; local cleanup still runs.
    } finally {
      // Clear the active-org header off the shared axios singleton so it can't leak into
      // the next session's requests before a new org is selected.
      api.removeHeader(ORGANIZATION_HEADER);
      queryClient.clear();
      setToken(null);
      setIsLoggingOut(false);
    }
  }, [queryClient, setToken]);

  return { logout, isLoggingOut };
}
