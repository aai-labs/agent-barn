"use client";

import { useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  CircleAlert,
  RefreshCw,
} from "lucide-react";
import { toast } from "sonner";

import { formatDate } from "@/shared/date";

import {
  useAgentWebhookActions,
  useWebhookInvocations,
} from "../hooks/use-agent-webhooks";
import type { WebhookInvocation } from "../schemas";

const STATUS_LABEL = {
  RECEIVED: "Submitting",
  SUBMITTED: "Submitted",
  DISPATCH_FAILED: "Not submitted",
} as const;

// Mirrors the API's STALLED_DISPATCH_AFTER: a submission still RECEIVED after this
// long was abandoned by the API process and may be retried.
const STALLED_DISPATCH_AFTER_MS = 2 * 60 * 1000;

function isRetryable(invocation: WebhookInvocation): boolean {
  if (invocation.status === "DISPATCH_FAILED") return true;
  return (
    invocation.status === "RECEIVED" &&
    Date.now() - Date.parse(invocation.updatedAt) > STALLED_DISPATCH_AFTER_MS
  );
}

export function WebhookInvocationHistory({
  agentId,
  webhookId,
  canRetry,
}: {
  agentId: string;
  webhookId: string;
  canRetry: boolean;
}) {
  const query = useWebhookInvocations(agentId, webhookId);
  const { retryInvocation } = useAgentWebhookActions();
  const [expandedId, setExpandedId] = useState<string | null>(null);

  async function retry(invocationId: string) {
    try {
      await retryInvocation.mutateAsync({ agentId, webhookId, invocationId });
    } catch (error) {
      toast.error(
        error instanceof Error
          ? error.message
          : "Could not retry the submission.",
      );
    }
  }

  return (
    <div className="af-card p-5">
      <h3 className="m-0 text-sm font-semibold text-[var(--ink)]">
        Invocations{" "}
        {query.total > 0 && (
          <span className="font-normal text-[var(--ink-4)]">
            ({query.total})
          </span>
        )}
      </h3>
      <p className="mb-4 mt-1 text-xs text-[var(--ink-4)]">
        Submission history only. Execution and delivery history remain in the
        selected native runtime.
      </p>
      {query.isPending && (
        <p className="m-0 text-sm text-[var(--ink-3)]">Loading invocations…</p>
      )}
      {query.error && (
        <div
          className="flex items-center gap-2 text-sm text-[var(--err)]"
          role="alert"
        >
          <CircleAlert size={15} /> Could not load invocations.
          <button
            type="button"
            className="af-btn af-btn-sm"
            onClick={() => void query.refetch()}
          >
            Retry
          </button>
        </div>
      )}
      {!query.isPending && !query.error && query.invocations.length === 0 && (
        <p className="m-0 text-sm text-[var(--ink-3)]">No invocations yet.</p>
      )}
      <div className="flex flex-col divide-y divide-[var(--line)]">
        {query.invocations.map((invocation) => (
          <InvocationRow
            key={invocation.id}
            invocation={invocation}
            expanded={expandedId === invocation.id}
            retrying={
              retryInvocation.isPending &&
              retryInvocation.variables?.invocationId === invocation.id
            }
            canRetry={canRetry && isRetryable(invocation)}
            onToggle={() =>
              setExpandedId((current) =>
                current === invocation.id ? null : invocation.id,
              )
            }
            onRetry={() => void retry(invocation.id)}
          />
        ))}
      </div>
      {query.hasNextPage && (
        <button
          type="button"
          className="af-btn af-btn-sm mt-3"
          disabled={query.isFetchingNextPage}
          onClick={() => void query.fetchNextPage()}
        >
          {query.isFetchingNextPage ? "Loading…" : "Load more"}
        </button>
      )}
    </div>
  );
}

function InvocationRow({
  invocation,
  expanded,
  retrying,
  canRetry,
  onToggle,
  onRetry,
}: {
  invocation: WebhookInvocation;
  expanded: boolean;
  retrying: boolean;
  canRetry: boolean;
  onToggle: () => void;
  onRetry: () => void;
}) {
  const Chevron = expanded ? ChevronDown : ChevronRight;
  return (
    <div className="py-3">
      <button
        type="button"
        className="flex w-full items-start gap-2 text-left"
        aria-expanded={expanded}
        onClick={onToggle}
      >
        <Chevron size={15} className="mt-0.5 text-[var(--ink-4)]" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--ink-4)]">
            <span>{formatDate(invocation.createdAt)}</span>
            <span aria-hidden>·</span>
            <span>{STATUS_LABEL[invocation.status]}</span>
            {invocation.externalEventId && (
              <>
                <span aria-hidden>·</span>
                <code>{invocation.externalEventId}</code>
              </>
            )}
          </div>
          <div className="mt-0.5 truncate text-sm text-[var(--ink)]">
            {invocation.prompt}
          </div>
        </div>
      </button>
      {expanded && (
        <div className="ml-6 mt-3 flex flex-col gap-3">
          <div className="flex flex-wrap gap-4 text-xs text-[var(--ink-4)]">
            <span>Dispatch generation {invocation.dispatchGeneration}</span>
            <span>
              {invocation.dispatchAttemptCount} submission attempt
              {invocation.dispatchAttemptCount === 1 ? "" : "s"}
            </span>
            {invocation.nativeJobId && (
              <span>
                Native job: <code>{invocation.nativeJobId}</code>
              </span>
            )}
          </div>
          <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-lg bg-[var(--bg-soft)] p-3 text-xs text-[var(--ink-2)]">
            {invocation.prompt}
          </pre>
          {invocation.lastErrorMessage && (
            <div className="flex items-start gap-2 rounded-lg bg-[var(--err-soft)] p-3 text-xs text-[var(--err)]">
              <CircleAlert size={14} className="mt-0.5" />
              <span>
                {invocation.lastErrorCode && (
                  <strong>{invocation.lastErrorCode}: </strong>
                )}
                {invocation.lastErrorMessage}
              </span>
            </div>
          )}
          {canRetry && (
            <button
              type="button"
              className="af-btn af-btn-sm w-fit"
              disabled={retrying}
              onClick={onRetry}
            >
              <RefreshCw size={13} />{" "}
              {retrying ? "Retrying…" : "Retry submission"}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
