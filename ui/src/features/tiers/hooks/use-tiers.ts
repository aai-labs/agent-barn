"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/shared/api";

import { TierListSchema, TierSchema, type Tier, type TierCreate, type TierUpdate } from "../schemas";
import { tiersKey } from "../utils";

const BASE = "/api/v1/platform/tiers";

/** The tier catalog. Platform Administrators only. */
export function useTiers() {
  const query = useQuery({
    queryKey: tiersKey.platform,
    queryFn: async () => (await api.get<Tier[]>(BASE, { schema: TierListSchema })).data,
  });
  return {
    tiers: query.data ?? [],
    isLoadingTiers: query.isPending,
    tiersError: query.error,
    reloadTiers: query.refetch,
  };
}

/**
 * Create, edit and delete tiers. Each refreshes the catalog. Failures are left to the caller to
 * show beside what caused them, so there is no error toast here.
 */
export function useTierActions() {
  const queryClient = useQueryClient();
  const refresh = () => void queryClient.invalidateQueries({ queryKey: tiersKey.platform });

  const create = useMutation({
    mutationFn: async (data: TierCreate) => (await api.post<Tier>(BASE, data, { schema: TierSchema })).data,
    onSuccess: (tier) => {
      refresh();
      toast.success(`${tier.name} added`);
    },
  });

  const update = useMutation({
    mutationFn: async ({ id, data }: { id: string; data: TierUpdate }) =>
      (await api.patch<Tier>(`${BASE}/${id}`, data, { schema: TierSchema })).data,
    onSuccess: refresh,
  });

  const remove = useMutation({
    mutationFn: async (id: string) => {
      await api.delete(`${BASE}/${id}`);
    },
    onSuccess: refresh,
  });

  return { create, update, remove };
}
