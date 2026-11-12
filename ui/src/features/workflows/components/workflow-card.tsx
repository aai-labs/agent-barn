"use client";

import { Archive, Copy, History, MoreHorizontal, Pencil, Play, Workflow } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

import { type WorkflowSummary } from "../schemas";

const count = (value: number, noun: string) =>
  `${value} ${value === 1 ? noun : `${noun}s`}`;

export type WorkflowCardActions = {
  onOpen: () => void;
  onRun: () => void;
  onEdit: () => void;
  onDuplicate: () => void;
  onOpenLatestRun: () => void;
  onArchive: () => void;
};

/**
 * A saved workflow in the Organization's grid. Its name opens it; the menu edits, copies
 * or archives it, and Run starts it on an Agent chosen then.
 */
export function WorkflowCard({
  workflow,
  canCreate,
  canRun,
  onOpen,
  onRun,
  onEdit,
  onDuplicate,
  onOpenLatestRun,
  onArchive,
}: {
  workflow: WorkflowSummary;
  /** Whether this viewer may create workflows, which a copy is. */
  canCreate: boolean;
  canRun: boolean;
  } & WorkflowCardActions) {
  const { version } = workflow;
  return (
    <article
      aria-label={version.name}
      className="af-card flex h-full w-full flex-col p-6"
    >
      <div className="mb-4 flex w-full items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-[var(--accent-soft)] text-[var(--accent-ink)]">
          <Workflow size={19} aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <button
            type="button"
            className="line-clamp-2 break-words text-left text-lg font-semibold leading-snug hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-color)]"
            aria-label={`Open ${version.name}`}
            onClick={onOpen}
          >
            {version.name}
          </button>
          <p className="mt-1 flex flex-wrap items-center gap-x-2 text-xs text-[var(--ink-3)]">
            <span className="font-mono">v{version.number}</span>
            {workflow.archivedAt && (
              <span className="rounded-full bg-[var(--bg-soft)] px-2 py-0.5 font-medium">
                Archived
              </span>
            )}
          </p>
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className="af-btn af-btn-icon af-btn-sm shrink-0"
              aria-label={`Actions for ${version.name}`}
            >
              <MoreHorizontal size={16} />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {workflow.allowedActions.includes("save_version") && (
              <DropdownMenuItem onSelect={onEdit}>
                <Pencil size={15} /> Edit
              </DropdownMenuItem>
            )}
            {canCreate && (
              <DropdownMenuItem onSelect={onDuplicate}>
                <Copy size={15} /> Duplicate
              </DropdownMenuItem>
            )}
            <DropdownMenuItem onSelect={onOpenLatestRun}>
              <History size={15} /> Open latest run
            </DropdownMenuItem>
            {workflow.allowedActions.includes("archive") && (
              <>
                <DropdownMenuSeparator />
                <DropdownMenuItem variant="destructive" onSelect={onArchive}>
                  <Archive size={15} /> Archive
                </DropdownMenuItem>
              </>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      <p className="mb-5 line-clamp-3 break-words text-sm leading-relaxed text-[var(--ink-3)]">
        {version.description}
      </p>
      <div className="mt-auto flex w-full items-center justify-between gap-3 border-t border-[var(--line)] pt-4">
        <p className="min-w-0 text-xs text-[var(--ink-3)]">
          <span className="block truncate">
            {workflow.createdBy?.name
              ? `Created by ${workflow.createdBy.name}`
              : "Creator no longer a member"}
          </span>
          <span className="block">
            {count(version.stepCount, "step")} · {count(version.inputCount, "input")}
          </span>
        </p>
        <button
          type="button"
          className="af-btn af-btn-primary af-btn-sm shrink-0"
          aria-label={`Run ${version.name}`}
          disabled={!canRun || Boolean(workflow.archivedAt)}
          onClick={onRun}
        >
          <Play size={13} aria-hidden="true" /> Run
        </button>
      </div>
    </article>
  );
}
