import { ApiError } from "@/shared/api/error/errors";

import {
  AgentProvisioningError,
  AgentProvisioningErrorSchema,
} from "./schemas";

export type ProvisioningFailureDisplay = {
  title: string;
  summary: string;
  /** Bounded specifics from the cluster, such as the exhausted quota axis. */
  detail: string | null;
};

const TITLE_BY_CODE: Record<string, string> = {
  QUOTA_EXHAUSTED: "Namespace quota exhausted",
  CLUSTER_PERMISSION_DENIED: "Cluster permission denied",
  RESOURCE_REJECTED: "Cluster rejected the configuration",
  CLUSTER_UNAVAILABLE: "Cluster unreachable",
};

const FALLBACK_TITLE = "The agent couldn't start";

export function describeProvisioningFailure(
  failure: AgentProvisioningError,
): ProvisioningFailureDisplay {
  return {
    title: TITLE_BY_CODE[failure.code] ?? FALLBACK_TITLE,
    summary: failure.summary,
    detail: failure.detail ?? null,
  };
}

/**
 * Read a classified failure out of a rejected mutation.
 *
 * Returns null when the error is anything else — a validation failure, a lost
 * session, an unreachable API, etc.
 */
export function provisioningFailureOf(
  error: unknown,
): AgentProvisioningError | null {
  if (!(error instanceof ApiError)) return null;
  const parsed = AgentProvisioningErrorSchema.safeParse(error.details?.detail);
  return parsed.success ? parsed.data : null;
}

export function provisioningFailureLine(
  failure: AgentProvisioningError,
): string {
  return failure.summary;
}
