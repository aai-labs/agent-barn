"use client";

import { useQuery } from "@tanstack/react-query";

import { type TierHoldPreview, TierHoldPreviewSchema } from "@/features/tiers/schemas";
import { api } from "@/shared/api";

/** What moving to `tierKey` would put on hold, while a dialog asks to confirm it. */
export function useHoldPreview(organizationId: string, tierKey: string | null) {
  const query = useQuery({
    queryKey: ["subscription-hold-preview", organizationId, tierKey],
    queryFn: async () =>
      (
        await api.get<TierHoldPreview>(
          `/api/v1/organizations/${organizationId}/subscription/preview?tier_key=${encodeURIComponent(tierKey ?? "")}`,
          { schema: TierHoldPreviewSchema },
        )
      ).data,
    enabled: !!organizationId && !!tierKey,
    staleTime: 0,
  });
  return { preview: query.data ?? null, isLoading: query.isPending && !!tierKey, error: query.error };
}
