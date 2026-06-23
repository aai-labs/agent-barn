"use client";

import { useMutation } from "@tanstack/react-query";

import { api } from "@/shared/api";
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
  return useMutation({
    mutationFn: async (data: CreateSlackAppData) => {
      const response = await api.post<CreateSlackAppResponse>(
        "/api/v1/slack/apps",
        data,
        { schema: CreateSlackAppResponseSchema },
      );
      return response.data;
    },
  });
}
