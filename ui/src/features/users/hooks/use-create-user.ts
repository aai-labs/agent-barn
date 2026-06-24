"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";

import type { CreateUserData } from "../schemas";
import { usersKey } from "../utils";

export function useCreateUser() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (data: CreateUserData) => {
      const response = await api.post("/api/v1/users", {
        email: data.email,
        password: data.password,
        full_name: data.fullName || undefined,
      });
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: usersKey.lists() });
    },
  });
}
