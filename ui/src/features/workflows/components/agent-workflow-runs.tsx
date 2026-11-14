"use client";

import { PlayCircle } from "lucide-react";
import Link from "next/link";
import { parseAsString, useQueryState } from "nuqs";

import { workflowPageParser } from "../url-state";
import { WorkflowApprovalInbox } from "./workflow-approval-inbox";
import { WorkflowRunList } from "./workflow-run-list";
import { WorkflowRunDetail } from "./workflow-runs";

/**
 * An Agent's Workflows tab: the runs this Agent has run and the approvals they wait on.
 * Workflows themselves belong to the Organization and are created and started there.
 */
export function AgentWorkflowRuns({
  agentId,
  organizationId,
  canRun,
}: {
  agentId: string;
  organizationId: string;
  /** Whether the viewer may start runs on this Agent. */
  canRun: boolean;
}) {
  const [runId, setRunId] = useQueryState(
    "workflowRun",
    parseAsString.withDefault("").withOptions({ history: "push", scroll: false }),
  );
  const [page, setPage] = useQueryState("workflowRunPage", workflowPageParser);
  const workflows = `/dashboard/${organizationId}/workflows`;
  const startHref = `${workflows}?workflowsTab=workflows&agent=${agentId}`;
  if (runId)
    return (
      <div style={{ color: "var(--ink)" }}>
        <nav
          aria-label="Workflow navigation"
          className="flex flex-wrap items-center gap-2 text-sm text-[var(--ink-3)]"
        >
          <button
            type="button"
            className="hover:text-[var(--ink)]"
            aria-label="All workflows"
            onClick={() => void setRunId("")}
          >
            Workflows
          </button>
          <span aria-hidden="true">/</span>
          <span aria-current="page" className="text-[var(--ink)]">
            Run detail
          </span>
        </nav>
        <WorkflowRunDetail
          organizationId={organizationId}
          runId={runId}
          onOpenRun={(id) => void setRunId(id)}
        />
      </div>
    );
  return (
    <div style={{ color: "var(--ink)" }}>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">Workflows</h2>
          <p className="mt-1 text-sm text-[var(--ink-3)]">
            Runs this agent has carried out. Workflows are created and managed for the
            whole organization.
          </p>
        </div>
        <Link
          href={canRun ? startHref : workflows}
          className={canRun ? "af-btn af-btn-primary" : "af-btn"}
        >
          {canRun ? "Run a workflow" : "View workflows"}
        </Link>
      </div>
      <WorkflowApprovalInbox agentId={agentId} onOpen={(run) => void setRunId(run.id)} />
      <WorkflowRunList
        title="Recent runs"
        filters={{ agentId }}
        page={page}
        onPageChange={setPage}
        onOpen={(run) => void setRunId(run.id)}
        showAgent={false}
        empty={
          <div className="flex flex-col items-center pt-16 pb-12 text-center">
            <span className="mb-4 flex size-14 items-center justify-center rounded-2xl bg-[var(--bg-soft)] text-[var(--ink-3)]">
              <PlayCircle aria-hidden="true" size={24} />
            </span>
            <h3 className="text-lg font-semibold">No runs yet</h3>
            <p className="mt-2 max-w-sm text-sm text-[var(--ink-3)]">
              Runs appear here once this agent runs a{" "}
              <Link href={canRun ? startHref : workflows} className="underline hover:text-[var(--ink)]">
                workflow
              </Link>
              .
            </p>
          </div>
        }
      />
    </div>
  );
}
