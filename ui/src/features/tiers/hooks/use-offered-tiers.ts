"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { type PublicTier, PublicTierListSchema } from "../schemas";

/** The tiers offered to new organizations, as the pricing page lists them. */
export function useOfferedTiers() {
  const query = useQuery({
    queryKey: ["tiers", "offered"] as const,
    queryFn: async () => (await api.get<PublicTier[]>("/api/v1/tiers", { schema: PublicTierListSchema })).data,
  });
  return { tiers: query.data ?? [], isLoadingTiers: query.isPending, tiersError: query.error };
}
