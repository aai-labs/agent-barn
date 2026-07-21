"use client";

import { useQuery } from "@tanstack/react-query";
import { z } from "zod";

import { api } from "@/shared/api";

import { SharedCredentialBriefSchema, type SharedCredentialBrief } from "../schemas";
import { sharedCredentialsKey } from "../utils";

const BriefsArraySchema = z.array(SharedCredentialBriefSchema);

export function useSharedCredentialBriefs() {
  const query = useQuery({
    queryKey: sharedCredentialsKey.list({ scope: { type: "briefs" } }),
    queryFn: async () => {
      const response = await api.get<SharedCredentialBrief[]>(
        "/api/v1/shared-credentials/briefs",
        { schema: BriefsArraySchema },
      );
      return response.data;
    },
  });

  return {
    briefs: query.data ?? [],
    isLoading: query.isPending,
    error: query.error,
  };
}
