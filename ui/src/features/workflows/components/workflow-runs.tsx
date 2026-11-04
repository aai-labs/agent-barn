"use client";

import { WorkflowFiles } from "./workflow-files";
import { AgentFiles } from "@/features/artifacts/components/agent-files";
import { useState } from "react";
import { ChevronRight, Clock3, FileCheck2, Files, LayoutDashboard } from "lucide-react";
import { useQueryState } from "nuqs";
import { workflowPageParser } from "../url-state";
import { AppErrorState } from "@/components/app-error-state";
import { ConfirmationDialog } from "@/components/confirmation-dialog";
import {
  useWorkflowRun,
  useWorkflowRunActions,
  useWorkflowRuns,
} from "../hooks/use-workflow-runs";
import type { WorkflowFile, WorkflowRun } from "../run-schemas";
import { WorkflowPager } from "./workflow-pager";
import { WorkflowMarkdown } from "./workflow-markdown";
import { WorkflowRunTiming, stepTiming } from "./workflow-run-timing";
import { AttemptStatus, WorkflowRunActivity } from "./workflow-run-activity";
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
              {run.rerunOfRunId && " · Re-run"}
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
  canManageFiles,
  runId,
  canRunAgain,
  onOpenRun,
}: {
  agentId: string;
  agent: { id: string; name: string };
  agentHref: string;
  canManageFiles: boolean;
  runId: string;
  /** Whether this actor may start runs of the workflow; the server decides per run. */
  canRunAgain: boolean;
  onOpenRun: (id: string) => void;
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
      canManageFiles={canManageFiles}
      run={run.data}
      canRunAgain={canRunAgain}
      onOpenRun={onOpenRun}
    />
  );
}

function RunSummary({
  run,
  agentName,
  agentHref,
}: {
  run: WorkflowRun;
  agentName: string;
  agentHref: string;
}) {
  const current = run.steps.find((step) => step.state === "RUNNING");
  const note = (text: string) => (
    <p className="rounded-xl bg-[var(--bg-soft)] px-5 py-4 text-sm">{text}</p>
  );
  if (run.state === "SUCCEEDED")
    return (
      <section aria-label="Run summary" className="overflow-hidden">
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
      <RunCard embedded label="Run summary" title="Run cancelled">
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
        embedded
        label="Run summary"
        title={
          run.state === "FAILED" ? "Run failed" : "This run needs attention"
        }
      >
        <div className="space-y-4">
          {note(run.reason ?? "Completed step summaries are retained.")}
          {run.state === "BLOCKED" && (
            <div className="space-y-2 text-sm">
              <p className="font-semibold">What to do next</p>
              <p>Check the Agent’s chat and any connected systems for work the step may have already done. The step will not resume automatically.</p>
              <p>After checking, cancel this run to close it. If you still need the result, start a new run from the workflow page. Starting again may repeat actions.</p>
              {!run.allowedActions.includes("cancel") && <p>Ask someone with permission to manage this Agent to cancel or start a run.</p>}
            </div>
          )}
        </div>
      </RunCard>
    );
  return (
    <RunCard
      embedded
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
        <AttemptStatus run={run} agentName={agentName} agentHref={agentHref} />
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
  if (step.state === "PENDING" && ["QUEUED", "RUNNING"].includes(run.state))
    return (
      <RunCard embedded label="Step detail">
        <div className="flex flex-col items-center py-12 text-center">
          <span className="mb-4 flex size-14 items-center justify-center rounded-2xl bg-[var(--bg-soft)] text-[var(--ink-3)]">
            <Clock3 aria-hidden="true" size={24} />
          </span>
          <p className="text-xs font-semibold uppercase tracking-widest text-[var(--ink-3)]">
            Step {index + 1} of {run.steps.length}
          </p>
          <h4 className="mt-2 text-lg font-semibold">{step.name}</h4>
          <p className="mt-2 max-w-sm text-sm text-[var(--ink-3)]">
            Waiting for earlier work to finish. Results and files will appear here when this step runs.
          </p>
        </div>
      </RunCard>
    );
  return (
    <RunCard embedded label="Step detail">
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
  canManageFiles,
  run,
  canRunAgain,
  onOpenRun,
}: {
  agentId: string;
  agent: { id: string; name: string };
  agentHref: string;
  canManageFiles: boolean;
  run: WorkflowRun;
  canRunAgain: boolean;
  onOpenRun: (id: string) => void;
}) {
  const [selectedView, setSelectedView] = useState("summary");
  const showArtifacts = selectedView === "artifacts";
  const actions = useWorkflowRunActions(agentId);
  const [confirm, setConfirm] = useState(false);
  const [confirmRerun, setConfirmRerun] = useState(false);
  const [rerunRequestId] = useState(() => crypto.randomUUID());
  const selectedStep = run.steps.find((step) => step.id === selectedView);
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
            {canRunAgain && run.allowedActions.includes("rerun") && (
              <button
                className="af-btn af-btn-primary"
                onClick={() => setConfirmRerun(true)}
              >
                Run again
              </button>
            )}
          </>
        }
      />
      {run.rerunOfRunId && (
        <p className="-mt-4 mb-6 text-sm text-[var(--ink-3)]">
          Re-run of{" "}
          <button
            type="button"
            className="underline hover:text-[var(--ink)]"
            onClick={() => onOpenRun(run.rerunOfRunId!)}
          >
            run {run.rerunOfRunId.slice(0, 8)}
          </button>
          , with the same version and inputs.
        </p>
      )}
      {actions.rerun.error && (
        <AppErrorState
          error={actions.rerun.error}
          title="This run could not be run again"
        />
      )}
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
            aria-current={selectedView === "summary" ? "page" : undefined}
            aria-controls="workflow-run-panel"
            onClick={() => setSelectedView("summary")}
            className={`relative mb-6 flex w-full items-center gap-3 rounded-xl border p-4 text-left transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 ${selectedView === "summary" ? "border-[var(--ok-muted)] bg-[var(--ok-soft)]" : "border-[var(--line)] bg-[var(--bg-elev)] hover:bg-[var(--bg-soft)]"}`}
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
            {selectedView === "summary" && <RunViewConnector />}
          </button>
          <StepRail
            steps={run.steps}
            runState={run.state}
            attempt={run.attempt}
            selectedStepId={selectedStep?.id}
            onSelectStep={setSelectedView}
          />
          <button
            type="button"
            aria-label="All artifacts"
            aria-current={showArtifacts ? "page" : undefined}
            aria-controls="workflow-run-panel"
            onClick={() => setSelectedView("artifacts")}
            className={`relative mt-6 flex w-full items-center gap-3 rounded-xl border p-4 text-left transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 ${showArtifacts ? "border-[var(--ok-muted)] bg-[var(--ok-soft)]" : "border-[var(--line)] bg-[var(--bg-elev)] hover:bg-[var(--bg-soft)]"}`}
          >
            <span
              aria-hidden="true"
              className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-[var(--bg-soft)] text-[var(--ink-3)]"
            >
              <Files size={18} />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-semibold">All artifacts</span>
              <span className="mt-1 block text-xs text-[var(--ink-3)]">
                Files from every step
              </span>
            </span>
            <ChevronRight
              aria-hidden="true"
              size={16}
              className="shrink-0 text-[var(--ink-3)]"
            />
            {showArtifacts && <RunViewConnector />}
          </button>
        </nav>
        <section
          id="workflow-run-panel"
          aria-label="Selected run view"
          className="min-w-0 overflow-hidden rounded-2xl border border-[var(--line)] bg-[var(--bg-elev)]"
        >
          {showArtifacts ? (
            <div className="px-6 py-5">
              <h3 className="text-lg font-semibold">All artifacts</h3>
              <p className="mt-3 text-sm text-[var(--ink-3)]">
                Files published during this run, including work from unfinished
                steps. Step and final outputs are labeled below.
              </p>
              <AgentFiles
                canManageFiles={canManageFiles}
                key={run.id}
                agentId={agentId}
                runId={run.id}
                showHeading={false}
                fileLabels={Object.fromEntries(
                  run.steps.flatMap((step, index) =>
                    (step.artifacts ?? []).map((file) => [
                      file.artifactId,
                      run.finalArtifacts?.some(
                        (final) => final.artifactId === file.artifactId,
                      )
                        ? "Final output"
                        : `Step ${index + 1} · ${step.name}`,
                    ]),
                  ),
                )}
                polling={["QUEUED", "RUNNING", "CANCELLING"].includes(
                  run.state,
                )}
              />
            </div>
          ) : (
            <>
              <div className="min-w-0">
                {selectedStep ? (
                  <StepDetail run={run} step={selectedStep} />
                ) : (
                  <RunSummary run={run} agentName={agent.name} agentHref={agentHref} />
                )}
              </div>
              {!(selectedStep?.state === "PENDING" && ["QUEUED", "RUNNING"].includes(run.state)) && <>
              <WorkflowFiles
                agentId={agentId}
                title={selectedStep ? "Step input files" : "Run input files"}
                files={Array.from(
                  new Map(
                    [
                      ...Object.values(run.inputs).filter(
                        (value): value is WorkflowFile =>
                          typeof value === "object",
                      ),
                      ...(selectedStep
                        ? run.steps
                            .slice(0, run.steps.indexOf(selectedStep))
                            .flatMap((step) => step.artifacts ?? [])
                        : []),
                    ].map((file) => [file.artifactId, file]),
                  ).values(),
                )}
              />
              {selectedStep ? (
                <WorkflowFiles
                  agentId={agentId}
                  title="Step outputs"
                  description={selectedStep.outputDescription}
                  files={selectedStep.artifacts ?? []}
                />
              ) : (
                run.state === "SUCCEEDED" && (
                  <WorkflowFiles
                    agentId={agentId}
                    title="Final outputs"
                    description={run.finalOutputDescription}
                    files={run.finalArtifacts ?? []}
                  />
                )
              )}
              <WorkflowRunTiming run={run} />
              <WorkflowRunActivity agentId={agentId} run={run} />
              </>}
            </>
          )}
        </section>
      </div>
      <ConfirmationDialog
        open={confirmRerun}
        onOpenChange={setConfirmRerun}
        title="Run this workflow again?"
        description={
          <span className="block">
            This starts a new run of version {run.versionNumber} with the same
            inputs as this one. This run and its results stay in the history. Earlier actions may be repeated.
          </span>
        }
        cancelLabel="Not now"
        confirmLabel="Run again"
        isPending={actions.rerun.isPending}
        onConfirm={async () => {
          try {
            const started = await actions.rerun.mutateAsync({
              run,
              clientRequestId: rerunRequestId,
            });
            setConfirmRerun(false);
            onOpenRun(started.id);
          } catch {
            setConfirmRerun(false);
          }
        }}
      />
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
