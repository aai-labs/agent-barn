"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { createQueryKeyStructure } from "@/shared/query-keys";

import { OnboardingSchema, type Onboarding } from "../schemas";

const BASE = "/api/v1/onboarding";
// Account-scoped: onboarding belongs to the signed-in user, not the active organization.
const keys = createQueryKeyStructure("onboarding");
const KEY = keys.detail("current");

export function useOnboarding({ enabled = true }: { enabled?: boolean } = {}) {
  const query = useQuery({
    queryKey: KEY,
    queryFn: async () => (await api.get<Onboarding>(BASE, { schema: OnboardingSchema })).data,
    enabled,
  });
  return {
    onboarding: query.data,
    isLoadingOnboarding: query.isPending && enabled,
    onboardingError: query.error,
    reloadOnboarding: query.refetch,
  };
}

export function useOnboardingActions() {
  const client = useQueryClient();
  const setUpAgent = useMutation({
    mutationFn: async () =>
      (await api.post<Onboarding>(`${BASE}/agent`, undefined, { schema: OnboardingSchema })).data,
    onSuccess: (data) => client.setQueryData(KEY, data),
  });
  const complete = useMutation({
    mutationFn: async () => {
      await api.post(`${BASE}/complete`);
    },
    onSuccess: () => client.invalidateQueries({ queryKey: KEY }),
  });
  return { setUpAgent, complete };
}
