"use client";

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
        <div className="af-card p-8 text-center">
          <h2 className="text-lg font-semibold">
            {list.data.total ? "No workflows on this page" : "No workflows yet"}
          </h2>
          <p className="text-sm">
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
