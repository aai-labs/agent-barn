"use client";

import { Workflow } from "lucide-react";
import { AppErrorState } from "@/components/app-error-state";

import { useWorkflows } from "../hooks/use-workflows";
import { WorkflowCard } from "./workflow-card";
import { WorkflowPager } from "./workflow-pager";

/** Saved definitions; mounted only while the list is visible, so it reads only then. */
export function WorkflowList({
  agentId,
  agentName,
  page,
  onPageChange,
  onOpen,
}: {
  agentId: string;
  agentName: string;
  page: number;
  onPageChange: (page: number) => void;
  onOpen: (workflowId: string) => void;
}) {
  const list = useWorkflows(agentId, page);
  if (list.error)
    return (
      <AppErrorState
        error={list.error}
        title="We couldn’t load workflows"
        onRetry={() => void list.refetch()}
      />
    );
  return (
    <section aria-label="Saved workflows">
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
            {list.data.total ? "No workflows on this page" : "No workflows yet"}
          </h2>
          <p className="mt-2 max-w-sm text-sm text-[var(--ink-3)]">
            {list.data.total
              ? "Return to the first page to browse your workflows."
              : `Create a repeatable plan for ${agentName}.`}
          </p>
        </div>
      )}
      <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {list.data?.items.map((workflow) => (
          <li key={workflow.id} className="min-w-0">
            <WorkflowCard
              workflow={workflow}
              onOpen={() => onOpen(workflow.id)}
            />
          </li>
        ))}
      </ul>
      {list.data && (
        <div className="px-5">
          <WorkflowPager
            page={page}
            pageSize={list.data.pageSize}
            total={list.data.total}
            onChange={onPageChange}
          />
        </div>
      )}
    </section>
  );
}
