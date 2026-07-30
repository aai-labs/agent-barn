"use client";

import { useMutation } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import {
  CreateSlackAppResponseSchema,
  type CreateSlackAppResponse,
} from "@/features/account/schemas";

export type CreateSlackAppData = {
  name: string;
  description: string;
  backgroundColor: string;
};

export function useCreateSlackApp() {
  const orgApiBase = useOrganizationApiBase();
  return useMutation({
    mutationFn: async (data: CreateSlackAppData) => {
      const response = await api.post<CreateSlackAppResponse>(
        `${orgApiBase}/slack/apps`,
        data,
        { schema: CreateSlackAppResponseSchema },
      );
      return response.data;
    },
  });
}
