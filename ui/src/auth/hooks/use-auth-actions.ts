"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { ApiError } from "@/shared/api/error/errors";
import { api } from "@/shared/api";

import { Token, TokenSchema } from "../schemas";
import { useAuthStore } from "../providers/auth-store";
import { currentUserContextKey, currentUserKey } from "../utils";

export function useAuthActions() {
  const queryClient = useQueryClient();
  const { setToken, clearToken } = useAuthStore();

  const login = ({
    email,
    password,
  }: {
    email: string;
    password: string;
    onSuccess?: () => void;
    onError?: (error: ApiError) => void;
  }) => {
    const payload = new FormData();
    payload.append("username", email);
    payload.append("password", password);

    return api.post<Token>("/api/v1/auth/login", payload, {
      schema: TokenSchema,
      skipAuth: true,
    });
  };

  const logout = (_variables: { onSuccess?: () => void } = {}) => {
    void _variables;
    return api.post("/api/v1/auth/logout", undefined, { skipAuth: true });
  };

  const loginMutation = useMutation({
    mutationFn: login,
    onSuccess: (data, variables) => {
      setToken(data.data);
      queryClient.invalidateQueries({ queryKey: currentUserKey.all });
      queryClient.invalidateQueries({ queryKey: currentUserContextKey.all });
      variables.onSuccess?.();
    },
    onError: (error: ApiError, variables) => {
      variables.onError?.(error);
    },
  });

  const logoutMutation = useMutation({
    mutationFn: logout,
    onSuccess: (_data, variables) => {
      clearToken();
      queryClient.removeQueries({ queryKey: currentUserKey.all });
      queryClient.removeQueries({ queryKey: currentUserContextKey.all });
      variables?.onSuccess?.();
    },
    onError: () => {
      clearToken();
      queryClient.removeQueries({ queryKey: currentUserKey.all });
      queryClient.removeQueries({ queryKey: currentUserContextKey.all });
    },
  });

  return {
    login: loginMutation.mutate,
    isLoggingIn: loginMutation.isPending,
    loginError: loginMutation.error as ApiError | null,
    logout: logoutMutation.mutate,
    isLoggingOut: logoutMutation.isPending,
  };
}
