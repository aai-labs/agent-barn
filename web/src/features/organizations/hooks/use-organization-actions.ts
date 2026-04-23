"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { currentUserContextKey } from "@/auth/utils";

import {
  Organization,
  OrganizationCreate,
  OrganizationCreateSchema,
  OrganizationSchema,
} from "../schemas";

export function useOrganizationActions() {
  const queryClient = useQueryClient();

  const createOrganizationMutation = useMutation({
    mutationFn: async (payload: OrganizationCreate) => {
      const validatedPayload = OrganizationCreateSchema.parse(payload);
      const response = await api.post<Organization>(
        "/api/v1/organizations",
        validatedPayload,
        { schema: OrganizationSchema },
      );
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: currentUserContextKey.all });
    },
  });

  return {
    createOrganization: createOrganizationMutation.mutate,
    isCreatingOrganization: createOrganizationMutation.isPending,
  };
}
