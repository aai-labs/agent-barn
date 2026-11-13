import { Children, useState, type ReactNode } from "react";
import Link from "next/link";

import type { AgentRef, SourceState } from "../schemas";
import { SOURCE_STATE_TEXT, TONE_COLOR, type Tone } from "../utils";

/** A titled part of the page. `actions` sit beside the title and wrap under it on a phone. */
export function Section({
  title,
  description,
  actions,
  children,
  testId,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  testId: string;
}) {
  return (
    <section className="mb-6 min-w-0" data-testid={testId} aria-label={title}>
      <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
        <div className="min-w-0 flex-1 basis-[24rem]">
          <h2 className="m-0 text-[14px] font-semibold" style={{ color: "var(--ink)" }}>
            {title}
          </h2>
          {description && (
            <p className="m-0 mt-0.5 text-[12.5px]" style={{ color: "var(--ink-4)" }}>
              {description}
            </p>
          )}
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}

/** What a part of the page shows when it has nothing to list, or could not be read. */
export function EmptyRow({ children, state }: { children: ReactNode; state?: SourceState }) {
  const missing = state && state !== "available";
  return (
    <div
      className="af-card px-4 py-3.5 text-[13px]"
      style={{ color: "var(--ink-3)" }}
      data-testid={missing ? "source-missing" : "nothing-to-show"}
    >
      {missing ? `Not shown: this is ${SOURCE_STATE_TEXT[state]}.` : children}
    </div>
  );
}

export function StatusDot({ tone, label }: { tone: Tone; label?: string }) {
  return (
    <span
      className="inline-block h-2 w-2 flex-shrink-0 rounded-full"
      style={{ background: TONE_COLOR[tone] }}
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    />
  );
}

/**
 * The Agent a resource belongs to, with its Organization.
 *
 * The Organization links to its Platform page, never to the Organization's own Agent pages:
 * a Platform Administrator has no Membership there. An id with no live Agent behind it is
 * shown as the start of its id, enough to find it in the cluster.
 */
export function AgentLabel({ agent }: { agent: AgentRef }) {
  if (!agent.agentName) {
    return (
      <span style={{ color: "var(--ink-3)" }}>
        No live agent <code className="text-[12px]">agent-{agent.agentId.slice(0, 8)}</code>
      </span>
    );
  }
  return (
    <span className="min-w-0">
      <span className="font-medium" style={{ color: "var(--ink)" }}>
        {agent.agentName}
      </span>
      {agent.organizationId && agent.organizationName && (
        <>
          <span style={{ color: "var(--ink-4)" }}> · </span>
          <Link
            href={`/dashboard/platform/organizations/${agent.organizationId}`}
            className="underline-offset-2 hover:underline"
            style={{ color: "var(--ink-3)" }}
          >
            {agent.organizationName}
          </Link>
        </>
      )}
    </span>
  );
}

/** Rows shown before "Show all". */
export const ROWS_SHOWN_FIRST = 5;

/**
 * A list that shows its first rows and the rest on request, so one failure across the platform
 * does not push everything else off the page. `total` is how many rows there are; the page is
 * sent at most a hundred, worst first, and says so when there are more than it has.
 */
export function ExpandableList({
  total,
  summary,
  testId,
  className = "",
  children,
}: {
  total: number;
  summary?: ReactNode;
  testId?: string;
  className?: string;
  children: ReactNode;
}) {
  const [expanded, setExpanded] = useState(false);
  const rows = Children.toArray(children);
  const count = Math.max(total, rows.length);
  const canExpand = rows.length > ROWS_SHOWN_FIRST;
  const shown = expanded || !canExpand ? rows : rows.slice(0, ROWS_SHOWN_FIRST);
  const partial = (expanded || !canExpand) && count > rows.length;
  return (
    <ul className={`af-card m-0 list-none divide-y p-0 ${className}`} data-testid={testId}>
      {summary && (
        <li className="px-4 py-2.5 text-[13px] font-medium" data-testid="list-summary">
          {summary}
        </li>
      )}
      {shown}
      {(canExpand || partial) && (
        <li className="flex flex-wrap items-center gap-x-3 px-4 py-2 text-[12.5px]" style={{ color: "var(--ink-4)" }}>
          {partial && <span>Showing {rows.length} of {count}, worst first.</span>}
          {canExpand && (
            <button
              type="button"
              className="cursor-pointer font-medium underline-offset-2 hover:underline"
              style={{ color: "var(--ink-2)" }}
              onClick={() => setExpanded(!expanded)}
            >
              {expanded ? "Show fewer" : `Show all ${count}`}
            </button>
          )}
        </li>
      )}
    </ul>
  );
}
