"use client";

import { ArrowUpRight, Workflow } from "lucide-react";

import { type WorkflowSummary } from "../schemas";

const count = (value: number, noun: string) =>
  `${value} ${value === 1 ? noun : `${noun}s`}`;

/** A saved definition in the workflow grid; the whole card opens it. */
export function WorkflowCard({
  workflow,
  onOpen,
}: {
  workflow: WorkflowSummary;
  onOpen: () => void;
}) {
  const { version } = workflow;
  return (
    <button
      className="af-card af-card-hover group flex h-full w-full flex-col p-6 text-left focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--accent-color)]"
      aria-label={`Open ${version.name}`}
      onClick={onOpen}
    >
      <span className="mb-5 flex w-full items-center justify-between gap-3">
        <span className="flex size-10 items-center justify-center rounded-xl bg-[var(--accent-soft)] text-[var(--accent-ink)]">
          <Workflow size={19} aria-hidden="true" />
        </span>
        <span className="rounded-full bg-[var(--bg-soft)] px-2.5 py-1 text-xs font-medium text-[var(--ink-3)]">
          {workflow.archivedAt ? "Archived" : "Saved"}
        </span>
      </span>
      <span className="line-clamp-2 break-words text-lg font-semibold leading-snug">
        {version.name}
      </span>
      <span className="mt-2 mb-6 line-clamp-3 break-words text-sm leading-relaxed text-[var(--ink-3)]">
        {version.description}
      </span>
      <span className="mt-auto flex w-full items-center justify-between gap-3 border-t border-[var(--line)] pt-4 text-xs text-[var(--ink-3)]">
        <span className="flex flex-wrap gap-x-3 gap-y-1">
          <span>v{version.number}</span>
          <span>{count(version.stepCount, "step")}</span>
          <span>{count(version.inputCount, "input")}</span>
        </span>
        <ArrowUpRight
          size={17}
          className="shrink-0 text-[var(--ink)] transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5"
          aria-hidden="true"
        />
      </span>
    </button>
  );
}
