"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { templatesKey } from "../utils";

export function useDeleteTemplate() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (slug: string) => {
      await api.delete(`/api/v1/templates/${slug}`);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: templatesKey.all });
    },
  });
}
