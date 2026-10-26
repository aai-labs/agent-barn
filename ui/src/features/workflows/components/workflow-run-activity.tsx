"use client";

import { useEffect, useState, type CSSProperties } from "react";
import Link from "next/link";
import { AppErrorState } from "@/components/app-error-state";
import { useWorkflowRunHistory } from "../hooks/use-workflow-runs";
import { isRunProgressing, type WorkflowRun } from "../run-schemas";

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
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!live) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [live]);
  if (!attempt)
    return run.reason ? <p className="text-sm">{run.reason}</p> : null;
  return (
    <div className="space-y-3">
      <p className="text-sm tabular-nums text-[var(--ink-3)]">
        Attempt {attempt.number} of {attempt.limit} · running{" "}
        {clock(now - Date.parse(attempt.startedAt))} · times out in{" "}
        {clock(Date.parse(attempt.expiresAt) - now)}
      </p>
      {attempt.agentUnresponsive ? (
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
      ) : (
        run.reason && (
          <p className="rounded-xl px-5 py-4 text-sm" style={noteStyle("warn")}>
            {run.reason}
          </p>
        )
      )}
    </div>
  );
}

/** Newest-first run history, so failed attempts stay visible while the run retries or after it ends. */
export function WorkflowRunActivity({
  agentId,
  run,
}: {
  agentId: string;
  run: WorkflowRun;
}) {
  const history = useWorkflowRunHistory(
    agentId,
    run.id,
    run.revision,
    isRunProgressing(run.state),
  );
  if (history.error)
    return (
      <AppErrorState
        error={history.error}
        title="Couldn’t load run activity"
        onRetry={() => void history.refetch()}
        className="md:col-start-2"
      />
    );
  const items = [...(history.data?.items ?? [])].reverse();
  if (items.length === 0) return null;
  return (
    <section
      aria-label="Run activity"
      className="min-w-0 rounded-2xl border border-[var(--line)] bg-[var(--bg-elev)] px-6 py-4 md:col-start-2"
    >
      <h4 className="mb-3 text-sm font-semibold">Activity</h4>
      <ul className="space-y-2">
        {items.map((item) => (
          <li key={item.id} className="flex gap-3 text-sm">
            <time
              dateTime={item.createdAt}
              className="w-20 shrink-0 tabular-nums text-[var(--ink-3)]"
            >
              {new Date(item.createdAt).toLocaleTimeString()}
            </time>
            <span className="min-w-0">{item.detail}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
