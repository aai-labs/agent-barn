"use client";

import { Workflow } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";

import { useWorkflows, type WorkflowListFilter } from "../hooks/use-workflows";
import { type WorkflowSummary } from "../schemas";
import { WorkflowCard } from "./workflow-card";
import { WorkflowPager } from "./workflow-pager";

const FILTERS: { value: WorkflowListFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "mine", label: "Created by me" },
  { value: "archived", label: "Archived" },
];

const EMPTY: Record<WorkflowListFilter, string> = {
  all: "Create a repeatable plan any of your agents can run.",
  mine: "Workflows you create appear here.",
  archived: "Archived workflows appear here; their saved versions stay readable.",
};

/** The Organization's saved workflows; mounted only while the list is visible, so it reads only then. */
export function WorkflowList({
  page,
  onPageChange,
  filter,
  onFilterChange,
  canCreate,
  canRun,
  onOpen,
  onRun,
  onEdit,
  onDuplicate,
  onOpenLatestRun,
  onArchive,
}: {
  page: number;
  onPageChange: (page: number) => void;
  filter: WorkflowListFilter;
  onFilterChange: (filter: WorkflowListFilter) => void;
  canCreate: boolean;
  canRun: boolean;
  onOpen: (workflow: WorkflowSummary) => void;
  onRun: (workflow: WorkflowSummary) => void;
  onEdit: (workflow: WorkflowSummary) => void;
  onDuplicate: (workflow: WorkflowSummary) => void;
  onOpenLatestRun: (workflow: WorkflowSummary) => void;
  onArchive: (workflow: WorkflowSummary) => void;
}) {
  const list = useWorkflows(page, filter);
  return (
    <section aria-label="Saved workflows">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div role="group" aria-label="Filter workflows" className="flex flex-wrap gap-1.5">
          {FILTERS.map(({ value, label }) => (
            <button
              key={value}
              type="button"
              aria-pressed={filter === value}
              className={`rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${
                filter === value
                  ? "border-[var(--line-strong)] bg-[var(--bg-elev)] text-[var(--ink)] shadow-sm"
                  : "border-transparent text-[var(--ink-3)] hover:text-[var(--ink)]"
              }`}
              onClick={() => onFilterChange(value)}
            >
              {label}
            </button>
          ))}
        </div>
        {list.data && (
          <p className="text-xs text-[var(--ink-3)]">
            {list.data.total} {list.data.total === 1 ? "workflow" : "workflows"}
          </p>
        )}
      </div>
      {list.error && (
        <AppErrorState
          error={list.error}
          title="We couldn’t load workflows"
          onRetry={() => void list.refetch()}
        />
      )}
      {list.isPending && (
        <p className="af-card p-5" role="status">
          Loading workflows…
        </p>
      )}
      {list.data?.items.length === 0 && (
        <div className="flex flex-col items-center pt-16 pb-12 text-center">
          <span className="mb-4 flex size-14 items-center justify-center rounded-2xl bg-[var(--bg-soft)] text-[var(--ink-3)]">
            <Workflow aria-hidden="true" size={24} />
          </span>
          <h2 className="text-lg font-semibold">
            {list.data.total
              ? "No workflows on this page"
              : filter === "all"
                ? "No workflows yet"
                : "Nothing here"}
          </h2>
          <p className="mt-2 max-w-sm text-sm text-[var(--ink-3)]">
            {list.data.total
              ? "Return to the first page to browse your workflows."
              : EMPTY[filter]}
          </p>
        </div>
      )}
      <ul className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {list.data?.items.map((workflow) => (
          <li key={workflow.id} className="min-w-0">
            <WorkflowCard
              workflow={workflow}
              canCreate={canCreate}
              canRun={canRun}
              onOpen={() => onOpen(workflow)}
              onRun={() => onRun(workflow)}
              onEdit={() => onEdit(workflow)}
              onDuplicate={() => onDuplicate(workflow)}
              onOpenLatestRun={() => onOpenLatestRun(workflow)}
              onArchive={() => onArchive(workflow)}
            />
          </li>
        ))}
      </ul>
      {list.data && (
        <WorkflowPager
          page={page}
          pageSize={list.data.pageSize}
          total={list.data.total}
          onChange={onPageChange}
        />
      )}
    </section>
  );
}
