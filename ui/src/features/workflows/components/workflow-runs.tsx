"use client";

import { useState } from "react";
import { ChevronRight, FileCheck2, LayoutDashboard } from "lucide-react";
import { useQueryState } from "nuqs";
import { workflowPageParser } from "../url-state";
import { AppErrorState } from "@/components/app-error-state";
import { ConfirmationDialog } from "@/components/confirmation-dialog";
import {
  useWorkflowRun,
  useWorkflowRunActions,
  useWorkflowRuns,
} from "../hooks/use-workflow-runs";
import type { WorkflowRun } from "../run-schemas";
import { WorkflowPager } from "./workflow-pager";
import { WorkflowMarkdown } from "./workflow-markdown";
import { WorkflowRunTiming, stepTiming } from "./workflow-run-timing";
import {
  RunCard,
  RunPageHeader,
  RunStatusBadge,
  RunViewConnector,
  StatusBadge,
  StepRail,
  runTone,
} from "./workflow-run-parts";
import { runStateLabel } from "../run-schemas";

export function WorkflowRuns({
  agentId,
  workflowId,
  onOpen,
}: {
  agentId: string;
  workflowId: string;
  onOpen: (id: string) => void;
}) {
  const [page, setPage] = useQueryState("workflowRunPage", workflowPageParser);
  const runs = useWorkflowRuns(agentId, workflowId, page);
  if (runs.error)
    return (
      <AppErrorState
        error={runs.error}
        title="Couldn’t load runs"
        onRetry={() => void runs.refetch()}
      />
    );
  if (!runs.data) return <p role="status">Loading runs…</p>;
  return (
    <section aria-label="Workflow runs" className="space-y-4">
      {runs.data.items.length === 0 && (
        <p>
          No runs yet. Run a saved version to see progress and text results
          here.
        </p>
      )}
      {runs.data.items.map((run) => (
        <button
          key={run.id}
          className="w-full rounded-2xl border border-[var(--line)] bg-[var(--bg-elev)] p-5 text-left flex flex-wrap items-center justify-between gap-3 hover:border-[var(--line-strong)]"
          onClick={() => onOpen(run.id)}
        >
          <span>
            <strong>{run.name}</strong>
            <span className="block text-sm text-[var(--ink-3)]">
              Version {run.versionNumber} ·{" "}
              {new Date(run.createdAt).toLocaleString()}
            </span>
          </span>
          <span className="flex items-center gap-3 text-sm text-[var(--ink-3)]">
            {run.nextStep}/{run.steps.length} steps
            <StatusBadge tone={runTone(run.state)}>
              {runStateLabel(run.state)}
            </StatusBadge>
          </span>
        </button>
      ))}
      <WorkflowPager
        page={page}
        pageSize={runs.data.pageSize}
        total={runs.data.total}
        onChange={setPage}
        noun="runs"
      />
    </section>
  );
}

export function WorkflowRunDetail({
  agentId,
  agent,
  agentHref,
  runId,
}: {
  agentId: string;
  agent: { id: string; name: string };
  agentHref: string;
  runId: string;
}) {
  const run = useWorkflowRun(agentId, runId);
  if (run.error)
    return (
      <AppErrorState
        error={run.error}
        title="This run is unavailable"
        onRetry={() => void run.refetch()}
      />
    );
  if (!run.data) return <p role="status">Loading run…</p>;
  return (
    <RunContents
      key={runId}
      agentId={agentId}
      agent={agent}
      agentHref={agentHref}
      run={run.data}
    />
  );
}

function RunSummary({
  run,
  agentName,
}: {
  run: WorkflowRun;
  agentName: string;
}) {
  const current = run.steps.find((step) => step.state === "RUNNING");
  const note = (text: string) => (
    <p className="rounded-xl bg-[var(--bg-soft)] px-5 py-4 text-sm">{text}</p>
  );
  if (run.state === "SUCCEEDED")
    return (
      <section
        aria-label="Run summary"
        className="overflow-hidden rounded-2xl border border-[var(--ok-muted)] bg-[var(--bg-elev)]"
      >
        <div
          className="px-6 py-5"
          style={{ background: "var(--ok-soft)", color: "var(--ink)" }}
        >
          <h4 className="text-lg font-semibold">Run completed</h4>
        </div>
        <div className="space-y-3 px-6 py-5">
          {run.finalSummary ? (
            <>
              <p className="text-[11px] font-semibold uppercase tracking-widest text-[var(--ink-3)]">
                Summary from {agentName}
              </p>
              <WorkflowMarkdown text={run.finalSummary} />
            </>
          ) : (
            <p className="text-sm text-[var(--ink-3)]">
              All steps completed. No summary was recorded.
            </p>
          )}
          {run.settledAt && (
            <p className="text-xs text-[var(--ink-3)]">
              Completed {new Date(run.settledAt).toLocaleString()}
            </p>
          )}
        </div>
      </section>
    );
  if (run.state === "CANCELLED")
    return (
      <RunCard label="Run summary" title="Run cancelled">
        <div className="space-y-4">
          {run.settledAt && (
            <p className="text-sm text-[var(--ink-3)]">
              Cancelled · {new Date(run.settledAt).toLocaleString()}
            </p>
          )}
          {note(
            "No further work is admitted. Completed step summaries are retained.",
          )}
        </div>
      </RunCard>
    );
  if (run.state === "FAILED" || run.state === "BLOCKED")
    return (
      <RunCard
        label="Run summary"
        title={
          run.state === "FAILED" ? "Run failed" : "This run needs attention"
        }
      >
        {note(run.reason ?? "Completed step summaries are retained.")}
      </RunCard>
    );
  return (
    <RunCard
      label="Run summary"
      title={
        run.state === "QUEUED"
          ? "Waiting to start"
          : run.state === "CANCELLING"
            ? "Stopping work"
            : `${agentName} is working on this run`
      }
    >
      <div className="space-y-4">
        <p className="text-sm text-[var(--ink-3)]">
          Step {Math.min(run.nextStep + 1, run.steps.length)} of{" "}
          {run.steps.length}
        </p>
        {current && (
          <div className="rounded-xl bg-[var(--bg-soft)] px-5 py-4">
            <p className="text-sm font-semibold">Current work</p>
            <p className="mt-1 text-sm">{current.name}</p>
          </div>
        )}
        {run.reason && <p className="text-sm">{run.reason}</p>}
      </div>
    </RunCard>
  );
}

function StepDetail({
  run,
  step,
}: {
  run: WorkflowRun;
  step: WorkflowRun["steps"][number];
}) {
  const index = run.steps.findIndex((item) => item.id === step.id);
  const stopped = ["CANCELLED", "FAILED", "BLOCKED", "PAUSED"].includes(
    run.state,
  );
  return (
    <RunCard label="Step detail">
      <p className="mb-2 text-[11px] font-semibold uppercase tracking-widest text-[var(--ink-3)]">
        Step {index + 1} of {run.steps.length}
      </p>
      <h4 className="mb-3 text-lg font-semibold">{step.name}</h4>
      {step.startedAt && step.completedAt && (
        <p className="mb-4 text-sm text-[var(--ink-3)]">
          Completed in {stepTiming(step, run.state)}
        </p>
      )}
      {step.summary ? (
        <WorkflowMarkdown text={step.summary} />
      ) : (
        <p className="text-sm text-[var(--ink-3)]">
          {step.state === "COMPLETED"
            ? "No result was recorded for this step."
            : stopped
              ? "No result was recorded before the run stopped."
              : step.state === "RUNNING"
                ? "This step is in progress. Its result will appear here when it finishes."
                : "This step has not started yet."}
        </p>
      )}
    </RunCard>
  );
}

function RunContents({
  agentId,
  agent,
  agentHref,
  run,
}: {
  agentId: string;
  agent: { id: string; name: string };
  agentHref: string;
  run: WorkflowRun;
}) {
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);
  const actions = useWorkflowRunActions(agentId);
  const [confirm, setConfirm] = useState(false);
  const selectedStep = run.steps.find((step) => step.id === selectedStepId);
  const started = new Date(run.createdAt).toLocaleString();
  return (
    <section aria-label="Run detail">
      <RunPageHeader
        eyebrow={`${run.name} · v${run.versionNumber} · run ${run.id.slice(0, 8)}`}
        title={run.name}
        badge={<RunStatusBadge state={run.state} />}
        agent={agent}
        agentHref={agentHref}
        detail={`Started ${started}`}
        actions={
          <>
            {run.allowedActions.includes("cancel") && (
              <button className="af-btn" onClick={() => setConfirm(true)}>
                Cancel run
              </button>
            )}
          </>
        }
      />
      {actions.cancel.error && (
        <AppErrorState
          error={actions.cancel.error}
          title="Cancellation could not be recorded"
        />
      )}
      <div className="grid gap-x-8 gap-y-4 md:grid-cols-[minmax(200px,260px)_minmax(0,1fr)]">
        <nav aria-label="Run views" className="self-start md:sticky md:top-4">
          <button
            type="button"
            aria-label={
              run.state === "SUCCEEDED" ? "Result ready" : "Run overview"
            }
            aria-current={!selectedStep ? "page" : undefined}
            aria-controls="workflow-run-panel"
            onClick={() => setSelectedStepId(null)}
            className={`relative mb-6 flex w-full items-center gap-3 rounded-xl border p-4 text-left transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 ${!selectedStep ? "border-[var(--ok-muted)] bg-[var(--ok-soft)]" : "border-[var(--line)] bg-[var(--bg-elev)] hover:bg-[var(--bg-soft)]"}`}
          >
            <span
              aria-hidden="true"
              className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-[var(--bg-elev)] text-[var(--ok)]"
            >
              {run.state === "SUCCEEDED" ? (
                <FileCheck2 size={18} />
              ) : (
                <LayoutDashboard size={18} />
              )}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-semibold">
                {run.state === "SUCCEEDED" ? "Result ready" : "Run overview"}
              </span>
              <span className="mt-1 block text-xs text-[var(--ink-3)]">
                {run.state === "SUCCEEDED"
                  ? "View final summary"
                  : "View run progress"}
              </span>
            </span>
            <ChevronRight
              aria-hidden="true"
              size={16}
              className="shrink-0 text-[var(--ink-3)]"
            />
            {!selectedStep && <RunViewConnector />}
          </button>
          <StepRail
            steps={run.steps}
            runState={run.state}
            selectedStepId={selectedStepId}
            onSelectStep={setSelectedStepId}
          />
        </nav>
        <div className="contents">
          <div id="workflow-run-panel" className="min-w-0 [&>section]:h-full">
            {selectedStep ? (
              <StepDetail run={run} step={selectedStep} />
            ) : (
              <RunSummary run={run} agentName={agent.name} />
            )}
          </div>
          <WorkflowRunTiming run={run} />
        </div>
      </div>
      <ConfirmationDialog
        open={confirm}
        onOpenChange={setConfirm}
        title="Cancel this run?"
        description={
          <>
            <span className="block">
              {agent.name} will stop further work. Completed step summaries
              remain in the run history.
            </span>
          </>
        }
        cancelLabel="Keep running"
        confirmLabel="Cancel run"
        variant="destructive"
        isPending={actions.cancel.isPending}
        onConfirm={async () => {
          try {
            await actions.cancel.mutateAsync(run);
            setConfirm(false);
          } catch {
            setConfirm(false);
          }
        }}
      />
    </section>
  );
}
