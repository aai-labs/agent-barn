"use client";

import { useState } from "react";
import Link from "next/link";
import { BookOpenCheck, ExternalLink, FileText, Loader2, ScrollText } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { Badge, type BadgeVariant } from "@/components/badge";
import { ConfirmationDialog } from "@/components/confirmation-dialog";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { formatCallSpend, formatModelLabel, formatTokens } from "@/features/costs/format";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";
import { formatDate } from "@/shared/date";
import { toastError } from "@/shared/toast";

import { usePlaybookRun } from "../hooks/use-agent-playbook-runs";
import { useCancelPlaybookExtraction } from "../hooks/use-playbook-run-actions";
import type { PlaybookExtraction, PlaybookExtractionStatus } from "../schemas";
import { STATUS_LABEL, errorMessage, isActive } from "../utils";
import { ConventionsReviewDialog } from "./conventions-review-dialog";

const STATUS_VARIANT: Record<PlaybookExtractionStatus, BadgeVariant> = {
  QUEUED: "neutral",
  RUNNING: "accent",
  SUCCEEDED: "ok",
  FAILED: "danger",
  CANCELLED: "neutral",
};

function RunFacts({ run }: { run: PlaybookExtraction }) {
  const facts = [
    `${run.sessionCount} conversations`,
    `${run.messageCount} messages`,
    `${run.toolCallCount} tool calls`,
  ];
  if (run.memoryCount > 0) facts.push(`${run.memoryCount} memories`);
  if (run.promptTokens + run.completionTokens > 0)
    facts.push(`${formatTokens(run.promptTokens + run.completionTokens)} tokens`);
  if (run.costUsd !== null) facts.push(formatCallSpend(run.costUsd));
  if (run.model) facts.push(formatModelLabel(run.model));
  return (
    <div className="mt-1 text-[0.78rem]" style={{ color: "var(--ink-3)" }}>
      {facts.join(" · ")}
    </div>
  );
}

/** What a finished run produced: a playbook for this role, and conventions for every Agent. */
function RunOutputs({
  run,
  organizationId,
  onReviewConventions,
}: {
  run: PlaybookExtraction;
  organizationId: string | null;
  onReviewConventions: () => void;
}) {
  return (
    <div className="mt-3 grid gap-3 sm:grid-cols-2" data-testid="playbook-run-outputs">
      <div className="rounded-lg border p-3" style={{ borderColor: "var(--line)" }} aria-label="Role playbook" role="group">
        <div className="flex items-center gap-2 text-[0.88rem] font-medium">
          <BookOpenCheck size={15} aria-hidden style={{ color: "var(--accent-ink)" }} /> Role playbook
        </div>
        <p className="mb-3 mt-1 text-[0.8rem]" style={{ color: "var(--ink-3)" }}>
          How {run.sourceAgentName} does its job, for Agents in the same role. Saved as the unpublished Skill “
          {run.skillName}”.
        </p>
        {run.skillId && organizationId ? (
          <Link
            className="af-btn af-btn-sm af-btn-primary"
            href={`/dashboard/${organizationId}/settings/skills/${run.skillId}`}
          >
            <ExternalLink size={13} aria-hidden /> Review playbook
          </Link>
        ) : (
          <span className="text-[0.78rem]" style={{ color: "var(--ink-4)" }}>
            The Skill has since been deleted.
          </span>
        )}
      </div>
      <div
        className="rounded-lg border p-3"
        style={{ borderColor: "var(--line)" }}
        aria-label="Organization conventions"
        role="group"
      >
        <div className="flex items-center gap-2 text-[0.88rem] font-medium">
          <ScrollText size={15} aria-hidden style={{ color: "var(--accent-ink)" }} /> Organization conventions (
          {run.conventionCount})
        </div>
        <p className="mb-3 mt-1 text-[0.8rem]" style={{ color: "var(--ink-3)" }}>
          Rules for every Agent, whatever its role. You choose which Templates&apos; AGENTS.md they go into.
        </p>
        {run.conventionCount > 0 ? (
          <button type="button" className="af-btn af-btn-sm af-btn-primary" onClick={onReviewConventions}>
            <ScrollText size={13} aria-hidden /> Review conventions
          </button>
        ) : (
          <span className="text-[0.78rem]" style={{ color: "var(--ink-4)" }}>
            None found in these conversations.
          </span>
        )}
      </div>
    </div>
  );
}

function GeneratedPlaybookDialog({
  agentId,
  runId,
  onClose,
}: {
  agentId: string;
  runId: string | null;
  onClose: () => void;
}) {
  const { run, isLoadingRun, runError } = usePlaybookRun(agentId, runId);
  return (
    <Dialog open={runId !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Generated playbook</DialogTitle>
          <DialogDescription>
            Kept on the run because it could not be written as a draft. Copy what you need into the Skill.
          </DialogDescription>
        </DialogHeader>
        {isLoadingRun ? (
          <Loader2 size={16} className="animate-spin" aria-label="Loading playbook" />
        ) : runError ? (
          <AppErrorState error={runError} title="Could not load the playbook" />
        ) : (
          <pre
            className="max-h-[60vh] overflow-auto whitespace-pre-wrap rounded-lg border p-4 text-[0.8rem]"
            style={{ borderColor: "var(--line)", background: "var(--bg-soft)" }}
          >
            {run?.resultMarkdown ?? "This run has no generated playbook."}
          </pre>
        )}
      </DialogContent>
    </Dialog>
  );
}

export function PlaybookRunList({
  agentId,
  runs,
  isLoading,
  error,
  refetch,
  hasMore,
  loadMore,
  isLoadingMore,
}: {
  agentId: string;
  runs: PlaybookExtraction[];
  isLoading: boolean;
  error: unknown;
  refetch: () => unknown;
  hasMore: boolean;
  loadMore: () => unknown;
  isLoadingMore: boolean;
}) {
  const { selectedOrganization } = useOrganizationContext();
  const cancel = useCancelPlaybookExtraction(agentId);
  const [cancelTarget, setCancelTarget] = useState<PlaybookExtraction | null>(null);
  const [viewingRunId, setViewingRunId] = useState<string | null>(null);
  const [conventionsRunId, setConventionsRunId] = useState<string | null>(null);

  async function confirmCancel() {
    if (!cancelTarget) return;
    try {
      await cancel.mutateAsync(cancelTarget.id);
      setCancelTarget(null);
    } catch (caught) {
      toastError(caught);
    }
  }

  return (
    <section className="af-card mt-5 overflow-hidden" aria-label="Playbook runs">
      <h3 className="m-0 border-b px-5 py-3 text-[0.95rem] font-semibold" style={{ borderColor: "var(--line)" }}>
        Runs
      </h3>
      {isLoading ? (
        <div className="px-5 py-4 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
          Loading runs…
        </div>
      ) : error ? (
        <div className="p-5">
          <AppErrorState error={error} title="Could not load playbook runs" onRetry={() => void refetch()} />
        </div>
      ) : runs.length === 0 ? (
        <div className="px-5 py-4 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
          No playbooks have been extracted from this Agent yet.
        </div>
      ) : (
        <ul className="m-0 list-none p-0">
          {runs.map((run) => (
            <li
              key={run.id}
              className="border-b px-5 py-4 last:border-b-0"
              style={{ borderColor: "var(--line)" }}
              data-testid="playbook-run"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{run.skillName}</span>
                    <Badge variant={STATUS_VARIANT[run.status]}>
                      {isActive(run) && <Loader2 size={11} className="animate-spin" aria-hidden />}
                      {STATUS_LABEL[run.status]}
                    </Badge>
                    <span className="text-[0.78rem]" style={{ color: "var(--ink-4)" }}>
                      {formatDate(run.createdAt)}
                    </span>
                  </div>
                  <RunFacts run={run} />
                  {run.status === "FAILED" && (
                    <p className="mb-0 mt-1 text-[0.8rem]" style={{ color: "var(--err)" }}>
                      {errorMessage(run.errorCode)}
                    </p>
                  )}
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  {isActive(run) && (
                    <button type="button" className="af-btn af-btn-sm" onClick={() => setCancelTarget(run)}>
                      Cancel
                    </button>
                  )}
                  {run.errorCode === "draft_conflict" && (
                    <button type="button" className="af-btn af-btn-sm" onClick={() => setViewingRunId(run.id)}>
                      <FileText size={13} aria-hidden /> View playbook
                    </button>
                  )}
                </div>
              </div>
              {run.status === "SUCCEEDED" && (
                <RunOutputs
                  run={run}
                  organizationId={selectedOrganization?.id ?? null}
                  onReviewConventions={() => setConventionsRunId(run.id)}
                />
              )}
            </li>
          ))}
        </ul>
      )}
      {hasMore && (
        <footer className="border-t px-5 py-3" style={{ borderColor: "var(--line)" }}>
          <button type="button" className="af-btn af-btn-sm" disabled={isLoadingMore} onClick={() => void loadMore()}>
            {isLoadingMore ? "Loading…" : "Load more"}
          </button>
        </footer>
      )}
      <ConfirmationDialog
        open={cancelTarget !== null}
        onOpenChange={(open) => !open && setCancelTarget(null)}
        title="Cancel this run?"
        description="The run stops at its next step. Model calls already made are still billed to this Agent."
        confirmLabel="Cancel run"
        pendingLabel="Cancelling…"
        onConfirm={() => void confirmCancel()}
        isPending={cancel.isPending}
        variant="destructive"
      />
      <GeneratedPlaybookDialog agentId={agentId} runId={viewingRunId} onClose={() => setViewingRunId(null)} />
      <ConventionsReviewDialog agentId={agentId} runId={conventionsRunId} onClose={() => setConventionsRunId(null)} />
    </section>
  );
}
