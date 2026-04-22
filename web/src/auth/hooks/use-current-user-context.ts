"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { CurrentUserContext, CurrentUserContextSchema } from "../schemas";
import { currentUserContextKey } from "../utils";

export function useCurrentUserContext() {
  return useQuery({
    queryKey: currentUserContextKey.details(),
    queryFn: () =>
      api.get<CurrentUserContext>("/api/v1/auth/me", {
        schema: CurrentUserContextSchema,
      }),
    retry: false,
  });
}
