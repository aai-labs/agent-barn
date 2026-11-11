"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { currentUserContextKey } from "@/auth/utils";
import { agentsKey } from "@/features/agents/utils";
import { organizationsKey } from "@/features/organizations/utils";
import { api } from "@/shared/api";

import { type Subscription, SubscriptionPortalSchema, SubscriptionSchema, SubscriptionStartSchema } from "../schemas";
import { organizationBillingKey } from "./use-organization-billing";

/** Subscribe, switch tier, cancel at the period's end, or take a cancellation back. Each
 *  refreshes billing and the organization read, whose tier and entitlements change, and
 *  the signed-in user, whose trial a first subscription ends. */
export function useSubscriptionActions(
  organizationId: string,
  // Where a payment provider's page sends the owner back: Billing unless said otherwise.
  { returnTo }: { returnTo?: "billing" | "onboarding" } = {},
) {
  const queryClient = useQueryClient();
  const base = `/api/v1/organizations/${organizationId}/subscription`;
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: organizationBillingKey.all });
    void queryClient.invalidateQueries({ queryKey: organizationsKey.detail(organizationId) });
    void queryClient.invalidateQueries({ queryKey: agentsKey.all });
    void queryClient.invalidateQueries({ queryKey: currentUserContextKey.all });
  };

  const subscribe = useMutation({
    mutationFn: async (tierKey: string) =>
      (await api.post(base, returnTo ? { tierKey, returnTo } : { tierKey }, { schema: SubscriptionStartSchema })).data,
    onSuccess: (started) => {
      // A payment provider's page takes the payment; the subscription starts once it reports it.
      if (started.outcome === "redirect" && started.redirectUrl) window.location.assign(started.redirectUrl);
      refresh();
    },
  });
  const setCancel = useMutation({
    mutationFn: async (cancel: boolean) =>
      (await api.post<Subscription>(`${base}/${cancel ? "cancel" : "resume"}`, undefined, { schema: SubscriptionSchema }))
        .data,
    onSuccess: refresh,
  });
  const openPortal = useMutation({
    mutationFn: async () =>
      (await api.post(`${base}/portal`, undefined, { schema: SubscriptionPortalSchema })).data,
    onSuccess: (portal) => window.location.assign(portal.url),
  });
  return { subscribe, setCancel, openPortal };
}
