"use client";

import { AppErrorState } from "@/components/app-error-state";

import { useWorkflowVersions } from "../hooks/use-workflows";
import { type WorkflowVersion } from "../schemas";
import { WorkflowPager } from "./workflow-pager";

/** Immutable versions, newest first; mounted only while the history tab is open. */
export function WorkflowHistory({
  agentId,
  workflowId,
  currentNumber,
  page,
  onPageChange,
  onView,
}: {
  agentId: string;
  workflowId: string;
  currentNumber: number;
  page: number;
  onPageChange: (page: number) => void;
  onView: (version: WorkflowVersion) => void;
}) {
  const versions = useWorkflowVersions(agentId, workflowId, page);
  return (
    <section className="af-card p-5">
      <h2 className="text-lg font-semibold mb-4">Version history</h2>
      {versions.data && (
        <WorkflowPager
          page={page}
          pageSize={versions.data.pageSize}
          total={versions.data.total}
          onChange={onPageChange}
          noun="versions"
        />
      )}
      {versions.isPending && <p role="status">Loading versions…</p>}
      {versions.error && (
        <AppErrorState
          error={versions.error}
          title="We couldn’t load versions"
          onRetry={() => void versions.refetch()}
        />
      )}
      {!versions.error &&
        versions.data?.items.map((version) => (
          <div
            key={version.id}
            className="flex justify-between items-center border-t py-4"
            style={{ borderColor: "var(--line)" }}
          >
            <div>
              <strong>
                v{version.number}
                {version.number === currentNumber ? " · Current" : ""}
              </strong>
              <p className="text-sm">
                {version.draft.name} ·{" "}
                {new Date(version.createdAt).toLocaleString()}
              </p>
            </div>
            <button
              className="af-btn af-btn-sm"
              onClick={() => onView(version)}
            >
              View v{version.number}
            </button>
          </div>
        ))}
    </section>
  );
}
