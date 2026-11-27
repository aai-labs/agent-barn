"use client";

import { useState } from "react";
import { UserCheck, XCircle } from "lucide-react";
import { AppErrorState } from "@/components/app-error-state";
import { ConfirmationDialog } from "@/components/confirmation-dialog";
import { Textarea } from "@/components/ui/textarea";
import { useCurrentUser } from "@/auth/providers/user-context-provider";
import { useWorkflowRunActions } from "../hooks/use-workflow-runs";
import {
  waitingStepApproval,
  type WorkflowRun,
  type WorkflowStepApproval,
} from "../run-schemas";
import { WorkflowFiles } from "./workflow-files";
import { WorkflowMarkdown } from "./workflow-markdown";

const outcome: Record<
  Exclude<WorkflowStepApproval["state"], "WAITING">,
  { label: string; tone: string }
> = {
  APPROVED: { label: "Approved", tone: "var(--ok)" },
  CHANGES_REQUESTED: { label: "Changes requested", tone: "var(--warn)" },
  REJECTED: { label: "Rejected", tone: "var(--err)" },
  LAPSED: { label: "Closed without a decision", tone: "var(--ink-3)" },
};

/**
 * The decision at an Approval step, shown in the run's step pane: the result of the step
 * before it, what to check, and the allowed decisions for those who can edit the run's Agent.
 */
export function StepApprovalPanel({
  agentId,
  agentName,
  run,
}: {
  agentId: string;
  agentName: string;
  run: WorkflowRun;
}) {
  const { decideStep } = useWorkflowRunActions();
  const [note, setNote] = useState("");
  const [rejecting, setRejecting] = useState(false);
  const waiting = waitingStepApproval(run);
  if (!waiting) return null;
  const canDecide = run.allowedActions.includes("decide_step");
  const step = run.steps[waiting.stepIndex];
  // The workflow's author chose which decisions this step offers; older versions offer all.
  const allowed = step?.allowedDecisions ?? ["approve", "request_changes", "reject"];
  const changes = allowed.includes("request_changes");
  const rejects = allowed.includes("reject");
  const reviewed = run.steps[waiting.stepIndex - 1];
  const reviewedNumber = waiting.stepIndex;
  const submit = (decision: "approve" | "request_changes" | "reject") =>
    decideStep.mutateAsync({ run, decision, note });
  return (
    <section aria-label="Approval step" className="bg-[var(--bg-elev)]">
      <div className="flex items-center gap-4 px-6 py-5" style={{ background: "var(--warn-soft)" }}>
        <span
          className="flex size-10 shrink-0 items-center justify-center rounded-full text-white"
          style={{ background: "var(--warn)" }}
        >
          <UserCheck size={18} aria-hidden />
        </span>
        <div>
          <p
            className="text-[11px] font-bold uppercase tracking-widest"
            style={{ color: "var(--warn)" }}
          >
            Approval step {waiting.stepIndex + 1}
            {waiting.round > 1 ? ` · round ${waiting.round}` : ""}
          </p>
          <h3 className="text-xl font-semibold">
            Approve step {reviewedNumber} before the run continues?
          </h3>
          {/* The step's name stands on its own line so it never reads as part of the question. */}
          {reviewed && (
            <p className="mt-1 text-sm text-[var(--ink-2)]">
              Step {reviewedNumber}: {reviewed.name}
            </p>
          )}
        </div>
      </div>
      <div className="space-y-5 px-6 py-5">
        {step?.instructions && (
          <div>
            <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-widest text-[var(--ink-3)]">
              What to check
            </p>
            <p className="whitespace-pre-wrap text-sm">{step.instructions}</p>
          </div>
        )}
        {reviewed && (
          <div>
            <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-widest text-[var(--ink-3)]">
              Result of step {reviewedNumber}
              {reviewed.round && reviewed.round > 1 ? ` · revised ${reviewed.round - 1}×` : ""}
            </p>
            <div className="rounded-xl bg-[var(--bg-soft)] px-4 py-3">
              {reviewed.summary ? (
                <WorkflowMarkdown text={reviewed.summary} />
              ) : (
                <p className="text-sm text-[var(--ink-3)]">No result was recorded for this step.</p>
              )}
            </div>
            <div className="-mx-6">
              <WorkflowFiles
                agentId={agentId}
                unavailable={run.agentArchived}
                title={`Files from step ${reviewedNumber}`}
                files={reviewed.artifacts ?? []}
              />
            </div>
          </div>
        )}
        <StepApprovalRounds run={run} stepIndex={waiting.stepIndex} />
        {canDecide ? (
          <label className="block space-y-1.5 text-sm text-[var(--ink-3)]">
            <span>
              Notes for {agentName}
              {changes ? " (needed to request changes)" : " (optional)"}
            </span>
            <Textarea
              value={note}
              maxLength={4000}
              rows={3}
              onChange={(event) => setNote(event.target.value)}
              placeholder={
                changes
                  ? "What should change? An approval or rejection can carry a note too."
                  : "Anything to record with your decision?"
              }
            />
          </label>
        ) : (
          <p className="text-sm">
            Ask someone who can edit {agentName} to decide on this step.
          </p>
        )}
      </div>
      {canDecide && (
        <div className="flex flex-wrap items-center justify-between gap-4 border-t border-[var(--line)] bg-[var(--bg-soft)] px-6 py-4">
          <div className="flex flex-wrap gap-2">
            <button
              className="af-btn af-btn-primary"
              disabled={decideStep.isPending}
              onClick={() => void submit("approve").catch(() => undefined)}
            >
              Approve
            </button>
            {changes && (
              <button
                className="af-btn"
                disabled={decideStep.isPending || !note.trim()}
                onClick={() => void submit("request_changes").catch(() => undefined)}
              >
                Request changes
              </button>
            )}
            {rejects && (
              <button
                className="af-btn"
                style={{ color: "var(--err)", borderColor: "var(--err)" }}
                disabled={decideStep.isPending}
                onClick={() => setRejecting(true)}
              >
                Reject
              </button>
            )}
          </div>
          {changes && (
            <p className="max-w-sm text-right text-xs text-[var(--ink-3)]">
              Request changes runs step {reviewedNumber} again with your notes, then asks again.
            </p>
          )}
        </div>
      )}
      {decideStep.error && (
        <div className="px-6 pb-5">
          <AppErrorState error={decideStep.error} title="Your decision could not be recorded" />
        </div>
      )}
      <ConfirmationDialog
        open={rejecting}
        onOpenChange={setRejecting}
        title="Reject this run?"
        description={
          <span className="block">
            The run ends as rejected and no further steps run. Completed results stay in the
            run history{note.trim() ? ", with your note as the reason" : ""}.
          </span>
        }
        cancelLabel="Keep waiting"
        confirmLabel="Reject run"
        variant="destructive"
        icon={<XCircle size={18} />}
        isPending={decideStep.isPending}
        onConfirm={async () => {
          try {
            await submit("reject");
          } finally {
            setRejecting(false);
          }
        }}
      />
    </section>
  );
}

/** The decided rounds of an Approval step, oldest first. */
export function StepApprovalRounds({ run, stepIndex }: { run: WorkflowRun; stepIndex: number }) {
  const { user } = useCurrentUser();
  const decided = (run.stepApprovals ?? []).filter(
    (item) => item.stepIndex === stepIndex && item.state !== "WAITING",
  );
  if (decided.length === 0) return null;
  return (
    <section aria-label={`Decisions at step ${stepIndex + 1}`} className="mb-5 space-y-3">
      <h5 className="text-sm font-semibold">Decisions at this step</h5>
      {decided.map((item) => {
        const result = outcome[item.state as keyof typeof outcome];
        const who = item.decidedByUserId
          ? item.decidedByUserId === user?.id
            ? "You"
            : "Another member"
          : null;
        return (
          <div key={item.id} className="space-y-2 border-b border-[var(--line)] pb-3 last:border-0">
            <p className="flex flex-wrap justify-between gap-2 text-xs">
              <span className="font-semibold" style={{ color: result.tone }}>
                Round {item.round} · {result.label}
              </span>
              {who && item.decidedAt && (
                <span className="text-[var(--ink-3)]">
                  {who} · {new Date(item.decidedAt).toLocaleString()}
                </span>
              )}
            </p>
            {item.note && (
              <p className="rounded-lg bg-[var(--warn-soft)] px-3 py-2 text-sm">“{item.note}”</p>
            )}
          </div>
        );
      })}
    </section>
  );
}

/** Results of an Agent step that a person sent back with Request changes, oldest first. */
export function EarlierRounds({
  agentId,
  agentArchived,
  step,
}: {
  agentId: string;
  agentArchived: boolean;
  step: WorkflowRun["steps"][number];
}) {
  const rounds = step.earlierRounds ?? [];
  if (rounds.length === 0) return null;
  return (
    <section aria-label="Earlier rounds" className="mt-6 space-y-2">
      <h5 className="text-sm font-semibold">Earlier rounds</h5>
      <p className="text-xs text-[var(--ink-3)]">
        Results sent back with Request changes. Later steps use only the current round.
      </p>
      {rounds.map((round) => (
        <details
          key={round.round}
          className="rounded-xl border border-[var(--line)] px-4 py-3"
        >
          <summary className="cursor-pointer text-sm font-semibold">
            Round {round.round} · {new Date(round.completedAt).toLocaleString()}
          </summary>
          <div className="mt-3">
            {round.summary ? (
              <WorkflowMarkdown text={round.summary} />
            ) : (
              <p className="text-sm text-[var(--ink-3)]">No result was recorded.</p>
            )}
            <div className="-mx-6">
              <WorkflowFiles
                agentId={agentId}
                unavailable={agentArchived}
                title={`Round ${round.round} files`}
                files={round.artifacts}
              />
            </div>
          </div>
        </details>
      ))}
    </section>
  );
}
