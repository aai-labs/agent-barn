"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { type Subscription, SubscriptionSchema } from "@/features/billing/schemas";
import { api } from "@/shared/api";

import { platformOrganizationsKey } from "../utils";

/** An organization's live subscription, for Platform Administrators, and ending its period now. */
export function usePlatformSubscription(organizationId: string) {
  const queryClient = useQueryClient();
  const base = `/api/v1/platform/organizations/${organizationId}/subscription`;
  const key = [...platformOrganizationsKey.detail(organizationId), "subscription"] as const;
  const query = useQuery({
    queryKey: key,
    queryFn: async () => (await api.get<Subscription | null>(base, { schema: SubscriptionSchema.nullable() })).data,
  });
  const endPeriod = useMutation({
    mutationFn: async () =>
      (await api.post<Subscription | null>(`${base}/end-period`, undefined, { schema: SubscriptionSchema.nullable() }))
        .data,
    onSuccess: (subscription) => {
      queryClient.setQueryData(key, subscription);
      void queryClient.invalidateQueries({ queryKey: platformOrganizationsKey.detail(organizationId) });
    },
  });
  return { subscription: query.data ?? null, endPeriod };
}
