"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "@/shared/api";
import { createQueryKeyStructure } from "@/shared/query-keys";

import { CheckoutSchema, OrganizationBillingSchema, type OrganizationBilling } from "../schemas";

export const organizationBillingKey = createQueryKeyStructure("organization-billing");

// Credit arrives with the payment provider's confirmation, usually seconds after the
// owner is sent back; the page keeps reading until it has had time to.
const PAYMENT_POLL_MS = 5_000;
const PAYMENT_WAIT_MS = 60_000;

/** The organization's credit and history. Only its owner may read it, so callers pass
 *  `enabled: false` for anyone else rather than draw a refusal. `awaitingPayment` keeps
 *  it fresh for a minute after the owner comes back from paying. */
export function useOrganizationBilling(
  organizationId: string | undefined,
  { enabled = true, awaitingPayment = false } = {},
) {
  const [since] = useState(() => Date.now());
  const query = useQuery({
    refetchInterval: () => (awaitingPayment && Date.now() - since < PAYMENT_WAIT_MS ? PAYMENT_POLL_MS : false),
    queryKey: organizationBillingKey.detail(organizationId ?? ""),
    enabled: enabled && !!organizationId,
    queryFn: async () =>
      (
        await api.get<OrganizationBilling>(`/api/v1/organizations/${organizationId}/billing`, {
          schema: OrganizationBillingSchema,
        })
      ).data,
  });
  return {
    billing: query.data,
    isLoading: query.isPending && query.fetchStatus !== "idle",
    error: query.error,
    refetch: query.refetch,
  };
}

/** Starts a purchase: the API answers with the payment page to send the owner to. */
export function useStartCheckout(organizationId: string) {
  return useMutation({
    mutationFn: async (creditUsd: number) =>
      (
        await api.post<{ url: string }>(
          `/api/v1/organizations/${organizationId}/billing/checkout`,
          { creditUsd },
          { schema: CheckoutSchema },
        )
      ).data,
  });
}
