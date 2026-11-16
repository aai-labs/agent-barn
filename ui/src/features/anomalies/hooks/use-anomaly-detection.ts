"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";

import { AnomalyDetectionSettingsSchema, type AnomalyDetectionSettings } from "../schemas";
import { anomaliesKey } from "../utils";

/** Whether the active Organization checks its Agents for unusual activity. */
export function useAnomalyDetection() {
  const orgApiBase = useOrganizationApiBase();
  const { selectedOrganization } = useOrganizationContext();
  const organizationId = selectedOrganization?.id ?? "";

  const query = useQuery({
    queryKey: anomaliesKey.detection(organizationId),
    queryFn: async () => {
      const response = await api.get<AnomalyDetectionSettings>(`${orgApiBase}/anomaly-detection`, {
        schema: AnomalyDetectionSettingsSchema,
      });
      return response.data;
    },
    enabled: Boolean(organizationId),
  });

  return { settings: query.data, isLoading: query.isPending, error: query.error, refetch: query.refetch };
}

export function useUpdateAnomalyDetection() {
  const orgApiBase = useOrganizationApiBase();
  const { selectedOrganization } = useOrganizationContext();
  const queryClient = useQueryClient();
  const organizationId = selectedOrganization?.id ?? "";

  return useMutation({
    mutationFn: async (enabled: boolean) => {
      const response = await api.put<AnomalyDetectionSettings>(
        `${orgApiBase}/anomaly-detection`,
        { enabled },
        { schema: AnomalyDetectionSettingsSchema },
      );
      return response.data;
    },
    onSuccess: (settings) => {
      queryClient.setQueryData(anomaliesKey.detection(organizationId), settings);
      // Each Agent's Anomalies tab says whether checks are on.
      void queryClient.invalidateQueries({ queryKey: anomaliesKey.all });
    },
  });
}
