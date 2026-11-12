"use client";

import { useEffect, useRef, useState } from "react";
import { Hourglass, Pause } from "lucide-react";
import { AppErrorState } from "@/components/app-error-state";
import { Textarea } from "@/components/ui/textarea";
import { useCurrentUser } from "@/auth/providers/user-context-provider";
import { useWorkflowRunActions } from "../hooks/use-workflow-runs";
import { pendingApproval, type WorkflowRun } from "../run-schemas";

function remaining(ms: number): string {
  const seconds = Math.max(0, Math.round(ms / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

/** Seconds left on a live request, on the API's clock as of the last read. */
function useLiveCountdown(run: WorkflowRun, until: string | undefined) {
  const serverTime = run.attempt?.serverTime;
  const skew = useRef(0);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (serverTime) skew.current = Date.parse(serverTime) - Date.now();
  }, [serverTime]);
  useEffect(() => {
    if (!until) return;
    const timer = setInterval(() => setNow(Date.now() + skew.current), 1000);
    return () => clearInterval(timer);
  }, [until]);
  return until ? Date.parse(until) - now : 0;
}

/**
 * The decision gate for the exact command a step's Agent asked to run: answered live while
 * the session holds it, or after the session paused (parked) and waits for a person.
 */
export function WorkflowApproval({
  agentId,
  agentName,
  run,
}: {
  agentId: string;
  agentName: string;
  run: WorkflowRun;
}) {
  const { decide } = useWorkflowRunActions(agentId);
  const [guidance, setGuidance] = useState("");
  const approval = pendingApproval(run);
  const live = approval?.state === "LIVE";
  const left = useLiveCountdown(run, live ? approval?.liveUntil : undefined);
  if (!approval) return null;
  const canDecide = run.allowedActions.includes("decide");
  const step = run.steps[approval.stepIndex];
  const requested = new Date(approval.createdAt).toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  });
  const declines = (run.approvals ?? []).filter(
    (item) => item.stepIndex === approval.stepIndex && item.state === "DECLINED",
  ).length;
  const submit = (decision: "approve" | "decline") =>
    decide.mutate({
      run,
      decision,
      guidance: decision === "decline" ? guidance : undefined,
    });
  const Icon = live ? Hourglass : Pause;
  return (
    <section
      aria-label="Approval required"
      className="overflow-hidden rounded-2xl border-[1.5px] bg-[var(--bg-elev)] shadow-sm"
      style={{ borderColor: "var(--warn)" }}
    >
      <div
        className="flex flex-wrap items-center justify-between gap-4 px-6 py-5"
        style={{ background: "var(--warn-soft)" }}
      >
        <div className="flex items-center gap-4">
          <span
            className="flex size-10 shrink-0 items-center justify-center rounded-full text-white"
            style={{ background: "var(--warn)" }}
          >
            <Icon size={18} aria-hidden />
          </span>
          <div>
            <p
              className="text-[11px] font-bold uppercase tracking-widest"
              style={{ color: "var(--warn)" }}
            >
              {live ? "Approval required" : "Approval required · session paused"}
            </p>
            <h3 className="text-xl font-semibold">
              {live
                ? `Allow ${agentName} to run this command?`
                : `${agentName} stopped and is waiting for your decision`}
            </h3>
          </div>
        </div>
        {live && (
          <p className="text-right" role="timer" aria-live="off">
            <span
              className="block font-mono text-xl font-semibold tabular-nums"
              style={{ color: "var(--warn)" }}
            >
              {remaining(left)}
            </span>
            <span className="text-xs text-[var(--ink-3)]">left to answer live</span>
          </p>
        )}
      </div>
      <div className="space-y-4 px-6 py-5">
        <p className="text-[11px] font-semibold uppercase tracking-widest text-[var(--ink-3)]">
          {live ? "Exact command" : `Command ${agentName} asked to run · ${requested}`}
        </p>
        <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-all rounded-xl bg-[var(--bg-soft)] px-4 py-3 font-mono text-sm">
          {approval.command}
        </pre>
        <p className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-[var(--ink-3)]">
          {step && (
            <span>
              Step {approval.stepIndex + 1} · {step.name}
            </span>
          )}
          <span>The runtime supplies no target, parameters or reason beyond the command</span>
        </p>
        {!live && (
          <ol className="grid gap-3 sm:grid-cols-3">
            {[
              ["You decide", "The command was not released; the step stopped while it waited."],
              [`${agentName} resumes the same session`, "It sees your decision and its own earlier work."],
              ["You confirm live", `If ${agentName} asks again, the prompt appears here within seconds.`],
            ].map(([title, body], index) => (
              <li key={title} className="rounded-xl border border-[var(--line)] px-4 py-3">
                <span className="font-mono text-xs font-semibold" style={{ color: "var(--warn)" }}>
                  {index + 1}
                </span>
                <p className="text-sm font-semibold">{title}</p>
                <p className="text-xs text-[var(--ink-3)]">{body}</p>
              </li>
            ))}
          </ol>
        )}
        {canDecide ? (
          <label className="block space-y-1.5 text-sm text-[var(--ink-3)]">
            <span>Guidance for {agentName} (sent only if you decline)</span>
            <Textarea
              value={guidance}
              maxLength={4000}
              rows={2}
              onChange={(event) => setGuidance(event.target.value)}
              placeholder="What should the Agent do instead?"
            />
          </label>
        ) : (
          <p className="text-sm">
            Ask someone with permission to manage this Agent to approve or decline.
          </p>
        )}
      </div>
      {canDecide && (
        <div className="flex flex-wrap items-center justify-between gap-4 border-t border-[var(--line)] bg-[var(--bg-soft)] px-6 py-4">
          <div className="flex flex-wrap gap-2">
            <button
              className="af-btn af-btn-primary"
              disabled={decide.isPending}
              onClick={() => submit("approve")}
            >
              {live ? "Approve once" : "Approve & continue"}
            </button>
            <button
              className="af-btn"
              style={{ color: "var(--err)", borderColor: "var(--err)" }}
              disabled={decide.isPending}
              onClick={() => submit("decline")}
            >
              {live ? "Decline" : "Decline & continue"}
            </button>
          </div>
          <p className="text-right text-xs text-[var(--ink-3)]">
            {live
              ? `Requested ${requested}. No answer in time? The session pauses; nothing runs.`
              : `Declines so far in this step: ${declines} of 3`}
          </p>
        </div>
      )}
      {decide.error && (
        <div className="px-6 pb-5">
          <AppErrorState error={decide.error} title="Your decision could not be recorded" />
        </div>
      )}
    </section>
  );
}

const outcome = {
  RELEASED: { label: "Approved and sent to the Agent", tone: "var(--ok)" },
  APPROVED: { label: "Approved", tone: "var(--ok)" },
  DECLINED: { label: "Declined · never run", tone: "var(--err)" },
  LAPSED: { label: "Closed without a decision", tone: "var(--ink-3)" },
} as const;

/** The commands this step asked to run and what people decided, oldest first. */
export function StepApprovals({ run, stepIndex }: { run: WorkflowRun; stepIndex: number }) {
  const { user } = useCurrentUser();
  const decided = (run.approvals ?? []).filter(
    (item) => item.stepIndex === stepIndex && item.state in outcome,
  );
  if (decided.length === 0) return null;
  return (
    <section aria-label={`Approvals in step ${stepIndex + 1}`} className="mb-5 space-y-3">
      <h5 className="text-sm font-semibold">Approvals in this step</h5>
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
                {result.label}
              </span>
              {who && item.decidedAt && (
                <span className="text-[var(--ink-3)]">
                  {who} · {new Date(item.decidedAt).toLocaleString()}
                </span>
              )}
            </p>
            <pre className="whitespace-pre-wrap break-all rounded-lg bg-[var(--bg-soft)] px-3 py-2 font-mono text-xs">
              {item.command}
            </pre>
            {item.guidance && (
              <p className="rounded-lg bg-[var(--warn-soft)] px-3 py-2 text-sm">“{item.guidance}”</p>
            )}
          </div>
        );
      })}
    </section>
  );
}
