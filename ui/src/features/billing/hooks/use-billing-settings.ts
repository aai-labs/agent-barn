"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { createQueryKeyStructure } from "@/shared/query-keys";

import { BillingSettingsSchema, type BillingSettings } from "../schemas";

const BASE = "/api/v1/platform/settings/billing";
const KEY = createQueryKeyStructure("platform-billing-settings").detail("settings");

type BillingSettingsChange = Pick<
  BillingSettings,
  "paymentsEnabled" | "minPurchaseUsd" | "maxPurchaseUsd" | "creditRate" | "purchaseFeePercent"
>;

export function useBillingSettings() {
  const client = useQueryClient();
  const settings = useQuery({
    queryKey: KEY,
    queryFn: async () => (await api.get<BillingSettings>(BASE, { schema: BillingSettingsSchema })).data,
  });
  const save = useMutation({
    mutationFn: async (change: BillingSettingsChange) =>
      (await api.put<BillingSettings>(BASE, change, { schema: BillingSettingsSchema })).data,
    onSuccess: (data) => client.setQueryData(KEY, data),
  });
  return {
    billingSettings: settings.data,
    isLoading: settings.isPending,
    error: settings.error,
    reload: settings.refetch,
    saveSettings: save.mutateAsync,
    isSaving: save.isPending,
    saveError: save.error,
    resetSave: save.reset,
  };
}
