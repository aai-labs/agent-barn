"use client";

import { useQuery } from "@tanstack/react-query";

import { ArtifactLinkSchema, type ArtifactLink } from "@/features/artifacts/schemas";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { api } from "@/shared/api";

import { AgentTaskDetailSchema, type AgentTaskDetail, type AgentTaskFile } from "../schemas";
import { tasksKey } from "../utils";

/** One Task with its Notes and Files, loaded only when someone opens it. */
export function useAgentTask(agentId: string, taskId: string | null) {
  const orgApiBase = useOrganizationApiBase();
  const query = useQuery({
    queryKey: tasksKey.task(agentId, orgApiBase, taskId ?? ""),
    queryFn: async () =>
      (
        await api.get<AgentTaskDetail>(`${orgApiBase}/agents/${agentId}/tasks/${taskId}`, {
          schema: AgentTaskDetailSchema,
        })
      ).data,
    enabled: taskId !== null,
  });
  return { task: query.data, isLoading: query.isPending && query.fetchStatus !== "idle", error: query.error };
}

/**
 * Downloads a Task File: asks for a short-lived link to its Artifact and follows it, as the
 * Artifacts tab does. The link serves the file as an attachment under its own name.
 */
export function useDownloadTaskFile(agentId: string, taskId: string) {
  const orgApiBase = useOrganizationApiBase();

  return async function downloadTaskFile(file: AgentTaskFile) {
    const { data: link } = await api.get<ArtifactLink>(
      `${orgApiBase}/agents/${agentId}/tasks/${taskId}/files/${file.id}/download-link`,
      { schema: ArtifactLinkSchema },
    );
    window.location.assign(link.url);
  };
}
