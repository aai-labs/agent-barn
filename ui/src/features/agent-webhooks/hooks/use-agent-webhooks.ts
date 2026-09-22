"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";
import { api } from "@/shared/api";
import { createQueryKeyStructure } from "@/shared/query-keys";

import {
  AgentWebhookSchema,
  PaginatedWebhookInvocationsSchema,
  WebhookDeliveryPlatformReadSchema,
  WebhookInvocationSchema,
  type AgentWebhook,
  type PaginatedWebhookInvocations,
  type WebhookDeliveryPlatform,
  type WebhookDeliveryPlatformRead,
  type WebhookInvocation,
} from "../schemas";

export const agentWebhooksKey = createQueryKeyStructure("agent-webhooks");
export const webhookInvocationsKey = createQueryKeyStructure("webhook-invocations");
const PAGE_SIZE = 20;

export function useAgentWebhooks(agentId: string) {
  const orgApiBase = useOrganizationApiBase();
  const organizationId = useOrganizationContext().selectedOrganization?.id ?? "";
  return useQuery({
    queryKey: agentWebhooksKey.list({ organizationId, agentId }),
    queryFn: async () => {
      const response = await api.get<AgentWebhook[]>(`${orgApiBase}/agents/${agentId}/webhooks`, {
        schema: z.array(AgentWebhookSchema),
      });
      return response.data;
    },
    enabled: Boolean(agentId && organizationId),
  });
}

export function useWebhookDeliveryPlatforms(agentId: string) {
  const orgApiBase = useOrganizationApiBase();
  const organizationId = useOrganizationContext().selectedOrganization?.id ?? "";
  return useQuery({
    queryKey: agentWebhooksKey.detail(`${organizationId}:${agentId}:delivery-platforms`),
    queryFn: async () => {
      const response = await api.get<WebhookDeliveryPlatformRead[]>(
        `${orgApiBase}/agents/${agentId}/webhooks/delivery-platforms`,
        { schema: z.array(WebhookDeliveryPlatformReadSchema) },
      );
      return response.data;
    },
    enabled: Boolean(agentId && organizationId),
  });
}

export function useWebhookInvocations(agentId: string, webhookId: string) {
  const orgApiBase = useOrganizationApiBase();
  const organizationId = useOrganizationContext().selectedOrganization?.id ?? "";
  const query = useInfiniteQuery({
    queryKey: webhookInvocationsKey.list({ organizationId, agentId, webhookId }),
    queryFn: async ({ pageParam }) => {
      const response = await api.get<PaginatedWebhookInvocations>(
        `${orgApiBase}/agents/${agentId}/webhooks/${webhookId}/invocations?page=${pageParam}&page_size=${PAGE_SIZE}`,
        { schema: PaginatedWebhookInvocationsSchema },
      );
      return response.data;
    },
    initialPageParam: 1,
    getNextPageParam: (lastPage) =>
      lastPage.page < Math.ceil(lastPage.total / lastPage.pageSize) ? lastPage.page + 1 : undefined,
    enabled: Boolean(agentId && webhookId && organizationId),
  });
  return {
    ...query,
    invocations: query.data?.pages.flatMap((page) => page.items) ?? [],
    total: query.data?.pages[0]?.total ?? 0,
  };
}

export function useAgentWebhookActions() {
  const orgApiBase = useOrganizationApiBase();
  const organizationId = useOrganizationContext().selectedOrganization?.id ?? "";
  const queryClient = useQueryClient();
  const invalidate = (agentId: string) =>
    queryClient.invalidateQueries({ queryKey: agentWebhooksKey.list({ organizationId, agentId }) });

  const createWebhook = useMutation({
    mutationFn: async ({ agentId, ...body }: { agentId: string; displayName: string; deliveryPlatform: WebhookDeliveryPlatform }) => {
      const response = await api.post<AgentWebhook>(`${orgApiBase}/agents/${agentId}/webhooks`, body, {
        schema: AgentWebhookSchema,
      });
      return response.data;
    },
    onSuccess: (webhook) => invalidate(webhook.agentId),
  });

  const updateWebhook = useMutation({
    mutationFn: async ({ agentId, webhookId, ...body }: {
      agentId: string;
      webhookId: string;
      revision: number;
      displayName?: string;
      deliveryPlatform?: WebhookDeliveryPlatform;
      enabled?: boolean;
    }) => {
      const response = await api.patch<AgentWebhook>(
        `${orgApiBase}/agents/${agentId}/webhooks/${webhookId}`,
        body,
        { schema: AgentWebhookSchema },
      );
      return response.data;
    },
    onSuccess: (webhook) => invalidate(webhook.agentId),
  });

  const retireWebhook = useMutation({
    mutationFn: async ({ agentId, webhookId, revision }: { agentId: string; webhookId: string; revision: number }) => {
      await api.delete(`${orgApiBase}/agents/${agentId}/webhooks/${webhookId}?revision=${revision}`);
      return agentId;
    },
    onSuccess: invalidate,
  });

  const rotateSecret = useMutation({
    mutationFn: async ({ agentId, webhookId, revision }: { agentId: string; webhookId: string; revision: number }) => {
      const response = await api.post<AgentWebhook>(
        `${orgApiBase}/agents/${agentId}/webhooks/${webhookId}/rotate-secret?revision=${revision}`,
        undefined,
        { schema: AgentWebhookSchema },
      );
      return response.data;
    },
    onSuccess: (webhook) => invalidate(webhook.agentId),
  });

  const retryInvocation = useMutation({
    mutationFn: async ({ agentId, webhookId, invocationId }: { agentId: string; webhookId: string; invocationId: string }) => {
      const response = await api.post<WebhookInvocation>(
        `${orgApiBase}/agents/${agentId}/webhooks/${webhookId}/invocations/${invocationId}/retry`,
        undefined,
        { schema: WebhookInvocationSchema },
      );
      return response.data;
    },
    onSuccess: (_invocation, variables) =>
      queryClient.invalidateQueries({
        queryKey: webhookInvocationsKey.list({ organizationId, agentId: variables.agentId, webhookId: variables.webhookId }),
      }),
  });

  return { createWebhook, updateWebhook, retireWebhook, rotateSecret, retryInvocation };
}
