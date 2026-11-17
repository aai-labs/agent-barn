"use client";

import { useEffect, useRef, useState, type CSSProperties } from "react";
import Link from "next/link";
import { ScrollText } from "lucide-react";
import { AppErrorState } from "@/components/app-error-state";
import { useWorkflowRunHistory } from "../hooks/use-workflow-runs";
import type { WorkflowRun } from "../run-schemas";

function clock(ms: number): string {
  const seconds = Math.max(0, Math.round(ms / 1000));
  const minutes = Math.floor(seconds / 60);
  return minutes ? `${minutes}m ${seconds % 60}s` : `${seconds}s`;
}

const noteStyle = (tone: "warn" | "err"): CSSProperties => ({
  background: `var(--${tone}-soft)`,
  color: `var(--${tone})`,
});

/** Live attempt timing plus the latest retry reason or an unresponsive-Agent warning. */
export function AttemptStatus({
  run,
  agentName,
  agentHref,
}: {
  run: WorkflowRun;
  agentName: string;
  agentHref: string;
}) {
  const attempt = run.attempt;
  const live = Boolean(attempt);
  const serverTime = attempt?.serverTime;
  // The browser clock can be off, so times follow the API's clock as of the last read.
  const skew = useRef(0);
  const [now, setNow] = useState(() =>
    serverTime ? Date.parse(serverTime) : Date.now(),
  );
  useEffect(() => {
    if (serverTime) skew.current = Date.parse(serverTime) - Date.now();
  }, [serverTime]);
  useEffect(() => {
    if (!live) return;
    const timer = setInterval(() => setNow(Date.now() + skew.current), 1000);
    return () => clearInterval(timer);
  }, [live]);
  if (!attempt)
    return run.reason ? <p className="text-sm">{run.reason}</p> : null;
  return (
    <div className="space-y-3">
      <p className="text-sm tabular-nums text-[var(--ink-3)]">
        Attempt {attempt.number} · running{" "}
        {clock(now - Date.parse(attempt.startedAt))} · times out in{" "}
        {clock(Date.parse(attempt.expiresAt) - now)}
      </p>
      {attempt.agentUnresponsive && (
        <p
          role="alert"
          className="rounded-xl px-5 py-4 text-sm"
          style={noteStyle("err")}
        >
          <strong>{agentName} hasn’t accepted this step yet.</strong> If this
          persists, restart the Agent from{" "}
          <Link href={agentHref} className="underline">
            its page
          </Link>
          , then start a new run.
        </p>
      )}
      {run.reason && (
        <p className="rounded-xl px-5 py-4 text-sm" style={noteStyle("warn")}>
          {run.reason}
        </p>
      )}
    </div>
  );
}

type Tone = "ok" | "warn" | "err" | "muted";

/** How an event reads at a glance: green progress, amber waiting on a person, red trouble. */
function eventTone(kind: string, detail: string): Tone {
  if (kind === "APPROVAL_DECIDED") return detail.startsWith("Command declined") ? "err" : "ok";
  if (["STEP_COMPLETED", "APPROVAL_RELEASED"].includes(kind)) return "ok";
  if (["APPROVAL_REQUESTED", "APPROVAL_PARKED", "NEEDS_ATTENTION", "CANCEL_REQUESTED"].includes(kind))
    return "warn";
  if (["ATTEMPT_FAILED", "FENCED"].includes(kind)) return "err";
  return "muted";
}

const dotColor: Record<Tone, string> = {
  ok: "var(--ok)",
  warn: "var(--warn)",
  err: "var(--err)",
  muted: "var(--ink-4)",
};

// Approval events end in the exact command, which reads better set apart as code.
const COMMAND_EVENT = /^(Approval requested to run |Command (?:approved|declined): |Approved command released: |Waiting for approval to run )([\s\S]+)$/;

function EventText({ kind, detail }: { kind: string; detail: string }) {
  // The detail is the full Markdown summary, which belongs to the step.
  if (kind === "STEP_COMPLETED") return <>Step completed</>;
  const command = COMMAND_EVENT.exec(detail);
  if (!command) return <>{detail}</>;
  return (
    <>
      {command[1].replace(/:? $/, "")}{" "}
      <code
        title={command[2]}
        className="inline-block max-w-full truncate rounded bg-[var(--bg-soft)] px-1.5 py-0.5 align-bottom font-mono text-xs"
      >
        {command[2]}
      </code>
    </>
  );
}

/** Newest-first run history keeps failed attempts visible after they end. */
export function WorkflowRunActivity({
  agentId,
  run,
}: {
  agentId: string;
  run: WorkflowRun;
}) {
  const history = useWorkflowRunHistory(agentId, run.id, run.revision);
  if (history.error)
    return (
      <div className="border-t border-[var(--line)] px-6 py-4">
        <AppErrorState
          error={history.error}
          title="Couldn’t load run activity"
          onRetry={() => void history.refetch()}
        />
      </div>
    );
  const items = history.data?.items ?? [];
  if (items.length === 0) return null;
  return (
    <section
      aria-label="Run activity"
      className="min-w-0 border-t border-[var(--line)] px-6 py-4"
    >
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="flex items-center gap-2 text-sm font-semibold">
          <ScrollText size={15} aria-hidden className="text-[var(--ink-3)]" />
          Event log
        </h4>
        <p className="text-xs text-[var(--ink-3)]">Newest first · append-only</p>
      </div>
      <ul>
        {items.map((item) => (
          <li
            key={item.id}
            className="flex items-baseline gap-3 border-b border-[var(--line)] py-2.5 text-sm last:border-0"
          >
            <time
              dateTime={item.createdAt}
              title={new Date(item.createdAt).toLocaleString()}
              className="w-12 shrink-0 font-mono text-xs tabular-nums text-[var(--ink-3)]"
            >
              {new Date(item.createdAt).toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
                hour12: false,
              })}
            </time>
            <span
              aria-hidden="true"
              className="size-2 shrink-0 translate-y-[-1px] rounded-full"
              style={{ background: dotColor[eventTone(item.kind, item.detail)] }}
            />
            <span className="min-w-0 flex-1">
              <EventText kind={item.kind} detail={item.detail} />
              <span className="ml-2 font-mono text-xs text-[var(--ink-4)]">
                · {item.kind.toLowerCase()}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
