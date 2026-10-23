"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/shared/api";

import {
  AgentSizeListSchema,
  AgentSizeSchema,
  type AgentSize,
  type AgentSizeCreate,
  type AgentSizeUpdate,
} from "../schemas";
import { agentSizesKey } from "../utils";

const BASE = "/api/v1/platform/agent-sizes";

/** The Agent Size catalog. Platform Administrators only. */
export function useAgentSizes() {
  const query = useQuery({
    queryKey: agentSizesKey.platform,
    queryFn: async () => (await api.get<AgentSize[]>(BASE, { schema: AgentSizeListSchema })).data,
  });
  return {
    sizes: query.data ?? [],
    isLoadingSizes: query.isPending,
    sizesError: query.error,
    reloadSizes: query.refetch,
  };
}

/**
 * Create, edit and delete sizes. Each refreshes the catalog. Failures are left to the caller
 * to show beside what caused them, so there is no error toast here.
 */
export function useAgentSizeActions() {
  const queryClient = useQueryClient();
  const refresh = () => void queryClient.invalidateQueries({ queryKey: agentSizesKey.platform });

  const create = useMutation({
    mutationFn: async (data: AgentSizeCreate) =>
      (await api.post<AgentSize>(BASE, data, { schema: AgentSizeSchema })).data,
    onSuccess: (size) => {
      refresh();
      toast.success(`${size.name} added`);
    },
  });

  const update = useMutation({
    mutationFn: async ({ id, data }: { id: string; data: AgentSizeUpdate }) =>
      (await api.patch<AgentSize>(`${BASE}/${id}`, data, { schema: AgentSizeSchema })).data,
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
