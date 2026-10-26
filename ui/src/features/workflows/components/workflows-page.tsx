"use client";

import { useEffect, useState } from "react";
import { Archive, MoreHorizontal } from "lucide-react";
import Link from "next/link";
import { parseAsString, useQueryState } from "nuqs";

import { AppErrorState } from "@/components/app-error-state";
import { ConfirmationDialog } from "@/components/confirmation-dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAgent } from "@/features/agents/hooks/use-agent";
import { canAgent } from "@/features/agents/utils";
import { ApiError } from "@/shared/api/error/errors";

import {
  useWorkflow,
  useWorkflowActions,
  useWorkflowCapabilities,
} from "../hooks/use-workflows";
import {
  WorkflowDraftSchema,
  type WorkflowDraft,
  type WorkflowVersion,
} from "../schemas";
import { changedByOthers } from "../utils";
import { workflowPageParser, workflowViewParser } from "../url-state";
import {
  workflowApiProblems,
  workflowProblems,
  type WorkflowProblem,
} from "../validation";
import { emptyDraft, WorkflowEditor } from "./workflow-editor";
import { WorkflowHistory } from "./workflow-history";
import { WorkflowList } from "./workflow-list";
import { WorkflowSaveAlert } from "./workflow-save-alert";
import { WorkflowSnapshot } from "./workflow-snapshot";
import { WorkflowRunStart } from "./workflow-run-start";
import { WorkflowRunDetail, WorkflowRuns } from "./workflow-runs";

function errorMessage(error: unknown): string {
  if (error instanceof ApiError && Array.isArray(error.details?.detail)) {
    return error.details.detail
      .map(
        (item: { loc: (string | number)[]; msg: string }) =>
          `${item.loc.filter((part) => part !== "body").join(".")}: ${item.msg}`,
      )
      .join("\n");
  }
  return error instanceof Error
    ? error.message
    : "The request failed. Your draft is retained; try again.";
}
export function WorkflowsPage({
  agentId,
  organizationId,
  embedded = false,
  onStartingChange,
}: {
  agentId: string;
  organizationId: string;
  embedded?: boolean;
  /** Reports that the start-run screen replaces the surrounding Agent chrome. */
  onStartingChange?: (starting: boolean) => void;
}) {
  const {
    agent,
    error: agentError,
    isLoading,
    refetch: refetchAgent,
  } = useAgent(agentId);
  const [selected, setSelected] = useQueryState(
    "workflow",
    parseAsString
      .withDefault("")
      .withOptions({ history: "push", scroll: false }),
  );
  const [page, setPage] = useQueryState("workflowPage", workflowPageParser);
  const [editTarget, setEditTarget] = useState<{
    workflowId: string;
    revision: number;
    /** The saved draft this edit started from, to show what others changed. */
    base: WorkflowDraft;
  } | null>(null);
  const detail = useWorkflow(agentId, editTarget?.workflowId ?? selected);
  const [versionPage, setVersionPage] = useQueryState(
    "workflowVersionPage",
    workflowPageParser,
  );
  const capabilities = useWorkflowCapabilities(agentId);
  const actions = useWorkflowActions(agentId);
  const [draft, setDraft] = useState<WorkflowDraft | null>(null);
  const [editorSection, setEditorSection] = useState("details");
  const [problems, setProblems] = useState<WorkflowProblem[]>([]);
  const [attempted, setAttempted] = useState(false);
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState(false);
  const [notice, setNotice] = useState<string[]>([]);
  const [discard, setDiscard] = useState(false);
  const [archive, setArchive] = useState(false);
  const [historic, setHistoric] = useState<WorkflowVersion | null>(null);
  const [view, setView] = useQueryState("workflowView", workflowViewParser);
  const [, setRunPage] = useQueryState("workflowRunPage", workflowPageParser);
  const [startVersion, setStartVersion] = useState<WorkflowVersion | null>(
    null,
  );
  const [runId, setRunId] = useQueryState(
    "workflowRun",
    parseAsString
      .withDefault("")
      .withOptions({ history: "push", scroll: false }),
  );
  useEffect(() => {
    if (!startVersion) return;
    onStartingChange?.(true);
    return () => onStartingChange?.(false);
  }, [startVersion, onStartingChange]);
  const canAuthor =
    canAgent(agent, "agent.update") && capabilities.data?.authoring;
  const canRun = Boolean(
    capabilities.data?.execution &&
      detail.data?.executionAvailable &&
      canAgent(agent, "agent.update"),
  );
  const maySave =
    canAuthor &&
    (!editTarget ||
      (detail.data?.id === editTarget.workflowId &&
        detail.data.allowedActions.includes("save_version")));
  const pending = actions.save.isPending || actions.archive.isPending;
  const Heading = embedded ? "h2" : "h1";
  const home = `/dashboard/${organizationId}/agents/${agentId}`;
  const closeEditor = () => {
    setDraft(null);
    setEditorSection("details");
    setProblems([]);
    setAttempted(false);
    setEditTarget(null);
    setError("");
    setConflict(false);
    setNotice([]);
    setDiscard(false);
  };
  const changeDraft = (next: WorkflowDraft) => {
    setDraft(next);
    setProblems([]);
    setError("");
  };
  async function save() {
    if (!draft) return;
    setAttempted(true);
    const validated = WorkflowDraftSchema.safeParse(draft);
    if (!validated.success) {
      const issues = workflowProblems(validated.error.issues, draft);
      setProblems(issues);
      setEditorSection(issues[0].section);
      setError("Review these fields before saving. Your edits are retained.");
      return;
    }
    try {
      const saved = await actions.save.mutateAsync({
        draft: validated.data,
        workflowId: editTarget?.workflowId,
        revision: editTarget?.revision,
      });
      setDraft(null);
      setProblems([]);
      setAttempted(false);
      setEditTarget(null);
      setError("");
      setConflict(false);
      setNotice([]);
      setHistoric(null);
      setVersionPage(1);
      void setView("overview");
      void setSelected(saved.id);
    } catch (failure) {
      const issues = workflowApiProblems(failure, draft);
      setProblems(issues);
      if (issues.length) setEditorSection(issues[0].section);
      setError(
        issues.length
          ? "Review these fields before saving. Your edits are retained."
          : errorMessage(failure),
      );
      setConflict(failure instanceof ApiError && failure.status === 409);
    }
  }
  if (agentError)
    return (
      <AppErrorState
        error={agentError}
        title="This Agent is unavailable"
        onRetry={() => void refetchAgent()}
      />
    );
  if (isLoading || !agent) return <p role="status">Loading Agent…</p>;
  // The list owns its own read failure; a definition failure replaces every protected view.
  if ((selected || editTarget) && detail.error)
    return (
      <AppErrorState
        error={detail.error}
        title="We couldn’t load workflows"
        onRetry={() => void detail.refetch()}
      />
    );
  const editing = Boolean(draft);
  const current = historic ?? detail.data?.version;
  return (
    <div style={{ color: "var(--ink)" }}>
      <nav
        aria-label="Workflow navigation"
        className="flex flex-wrap items-center gap-2 text-sm text-[var(--ink-3)]"
      >
        {!embedded && (
          <>
            <Link href={home}>{agent.name}</Link>
            <span aria-hidden="true">/</span>
          </>
        )}
        {selected && !editing ? (
          <button
            className="hover:text-[var(--ink)]"
            aria-label="All workflows"
            onClick={() => {
              setHistoric(null);
              void setView(null);
              void setRunPage(null);
              setStartVersion(null);
              void setRunId("");
              void setSelected("");
            }}
          >
            Workflows
          </button>
        ) : !embedded ? (
          <span>Workflows</span>
        ) : null}
        {selected && !editing && (
          <>
            <span aria-hidden="true">/</span>
            {view === "overview" && !runId && !startVersion ? (
              <span
                aria-current="page"
                className="max-w-60 truncate text-[var(--ink)]"
              >
                {detail.data?.version.draft.name ?? "Workflow"}
              </span>
            ) : (
              <button
                type="button"
                className="max-w-60 truncate hover:text-[var(--ink)]"
                onClick={() => {
                  setStartVersion(null);
                  setHistoric(null);
                  void setView("overview");
                  void setRunId(null);
                }}
              >
                {detail.data?.version.draft.name ?? "Workflow"}
              </button>
            )}
            {(runId || view !== "overview" || startVersion) && (
              <span aria-hidden="true">/</span>
            )}
            {runId ? (
              <>
                <button
                  type="button"
                  aria-label="Back to runs"
                  className="hover:text-[var(--ink)]"
                  onClick={() => {
                    setStartVersion(null);
                    setHistoric(null);
                    void setView("runs");
                    void setRunId(null);
                  }}
                >
                  Runs
                </button>
                <span aria-hidden="true">/</span>
                <span aria-current="page" className="text-[var(--ink)]">
                  Run detail
                </span>
              </>
            ) : startVersion ? (
              <span aria-current="page">Start run</span>
            ) : view !== "overview" ? (
              <span aria-current="page" className="text-[var(--ink)]">
                {view === "runs" ? "Runs" : "Version history"}
              </span>
            ) : null}
          </>
        )}
      </nav>
      {!runId && !startVersion && (
        <>
          <div className="flex flex-wrap justify-between items-start gap-4 my-6">
            <div>
              <Heading className="text-3xl font-semibold tracking-tight">
                {editing
                  ? draft?.name || "Create a workflow"
                  : selected
                    ? current?.draft.name || "Workflow"
                    : "Workflows"}
              </Heading>
              <p className="text-sm mt-2" style={{ color: "var(--ink-3)" }}>
                {agent.name} ·{" "}
                {editing
                  ? "Unsaved draft"
                  : selected
                    ? `Saved v${current?.number ?? "…"}${detail.data?.archivedAt ? " · Archived" : ""}`
                    : "Your repeatable work"}
              </p>
            </div>
            <div className="flex gap-2 flex-wrap">
              {editing ? (
                <>
                  <button
                    className="af-btn"
                    disabled={pending}
                    onClick={() => setDiscard(true)}
                  >
                    Discard
                  </button>
                  {draft && (
                    <button
                      className="af-btn af-btn-primary"
                      disabled={!maySave || pending || draft.steps.length === 0}
                      onClick={() => void save()}
                    >
                      {actions.save.isPending ? "Saving…" : "Save workflow"}
                    </button>
                  )}
                </>
              ) : selected ? (
                <>
                  {detail.data?.allowedActions.includes("save_version") && (
                    <button
                      className="af-btn"
                      onClick={() => {
                        setHistoric(null);
                        setEditorSection("details");
                        setProblems([]);
                        setAttempted(false);
                        setDraft(structuredClone(detail.data!.version.draft));
                        setEditTarget({
                          workflowId: detail.data!.id,
                          revision: detail.data!.revision,
                          base: detail.data!.version.draft,
                        });
                        void setView("overview");
                      }}
                    >
                      {historic &&
                      historic.number !== detail.data.version.number
                        ? "Edit latest version"
                        : "Edit workflow"}
                    </button>
                  )}
                  <button
                    className="af-btn af-btn-primary"
                    disabled={!canRun}
                    onClick={() => {
                      if (detail.data)
                        setStartVersion(historic ?? detail.data.version);
                    }}
                  >
                    Run workflow
                  </button>
                  {detail.data?.allowedActions.includes("archive") && (
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <button
                          className="af-btn af-btn-icon"
                          aria-label="Workflow actions"
                        >
                          <MoreHorizontal size={18} />
                        </button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem
                          variant="destructive"
                          onSelect={() => setArchive(true)}
                        >
                          <Archive size={15} /> Archive workflow
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  )}
                </>
              ) : canAuthor ? (
                <button
                  className="af-btn af-btn-primary"
                  onClick={() => {
                    void setSelected("");
                    setEditTarget(null);
                    setEditorSection("details");
                    setProblems([]);
                    setAttempted(false);
                    setDraft(emptyDraft(""));
                    setError("");
                  }}
                >
                  + Create workflow
                </button>
              ) : null}
            </div>
          </div>
          <p className="text-sm mb-6" style={{ color: "var(--ink-3)" }}>
            {capabilities.data?.execution
              ? "Saving and running are separate. Each run uses the saved version and inputs you choose."
              : "Execution is unavailable. Saving a workflow will not start a run."}
          </p>
        </>
      )}
      {!canAuthor && (
        <p className="text-sm mb-6">
          {capabilities.data?.authoring === false
            ? "Workflow authoring is disabled for this installation."
            : "Read-only access. You can inspect saved workflow versions."}
        </p>
      )}
      {capabilities.error && (
        <AppErrorState
          error={capabilities.error}
          title="We couldn’t load authoring availability"
          onRetry={() => void capabilities.refetch()}
        />
      )}
      {error && (
        <WorkflowSaveAlert
          message={error}
          problems={problems}
          onSelect={setEditorSection}
          onLoadCurrent={
            conflict
              ? async () => {
                  const latest = await detail.refetch();
                  if (latest.data && editTarget) {
                    setNotice(
                      changedByOthers(
                        editTarget.base,
                        latest.data.version.draft,
                      ),
                    );
                    setEditTarget({
                      workflowId: latest.data.id,
                      revision: latest.data.revision,
                      base: latest.data.version.draft,
                    });
                    setConflict(false);
                    setError("");
                  }
                }
              : undefined
          }
        />
      )}
      {draft && editTarget && !error && notice.length > 0 && (
        <div role="status" className="af-card p-5 mb-5">
          <p>
            Current revision loaded. Your edits are retained; saving replaces
            these changes made since you started:
          </p>
          <ul className="mt-2 list-disc pl-5">
            {notice.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      )}
      {runId ? (
        <WorkflowRunDetail
          agentId={agentId}
          agent={agent}
          agentHref={home}
          runId={runId}
          canRunAgain={canRun}
          onOpenRun={(id) => {
            void setView("runs");
            void setRunId(id);
          }}
        />
      ) : startVersion && selected ? (
        <WorkflowRunStart
          agentId={agentId}
          agent={agent}
          workflowId={selected}
          version={startVersion}
          onBack={() => setStartVersion(null)}
          onStarted={(id) => {
            setStartVersion(null);
            void setView("runs");
            void setRunId(id);
          }}
        />
      ) : draft ? (
        <WorkflowEditor
          draft={draft}
          selected={editorSection}
          onSelect={setEditorSection}
          onChange={changeDraft}
          disabled={!maySave || pending}
          problems={problems}
          revealed={attempted}
        />
      ) : selected ? (
        detail.data && current ? (
          <Tabs
            value={view}
            onValueChange={(value) => {
              if (
                value !== "overview" &&
                value !== "runs" &&
                value !== "history"
              )
                return;
              void setView(value);
              if (value === "overview") setHistoric(null);
            }}
            className="gap-6"
          >
            <TabsList
              variant="line"
              aria-label="Workflow views"
              className="w-full justify-start border-b border-[var(--line)] p-0"
            >
              <TabsTrigger
                value="overview"
                className="h-full flex-none border-0 px-4 group-data-horizontal/tabs:after:bottom-[-1px]"
              >
                Overview
              </TabsTrigger>
              <TabsTrigger
                value="runs"
                className="h-full flex-none border-0 px-4 group-data-horizontal/tabs:after:bottom-[-1px]"
              >
                Runs
              </TabsTrigger>
              <TabsTrigger
                value="history"
                className="h-full flex-none border-0 px-4 group-data-horizontal/tabs:after:bottom-[-1px]"
              >
                Version history
              </TabsTrigger>
            </TabsList>
            <TabsContent value="history">
              <WorkflowHistory
                agentId={agentId}
                workflowId={detail.data.id}
                currentNumber={detail.data.version.number}
                page={versionPage}
                onPageChange={setVersionPage}
                onView={(version) => {
                  setHistoric(version);
                  void setView("overview");
                }}
              />
            </TabsContent>
            <TabsContent value="runs">
              <WorkflowRuns
                agentId={agentId}
                workflowId={detail.data.id}
                onOpen={(id) => {
                  void setView("runs");
                  void setRunId(id);
                }}
              />
            </TabsContent>
            <TabsContent value="overview">
              {historic && historic.number !== detail.data.version.number && (
                <div className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-xl bg-[var(--accent-soft)] px-5 py-3 text-sm">
                  <p>
                    Viewing saved v{historic.number}. The latest version is v
                    {detail.data.version.number}.
                  </p>
                  <button
                    className="af-btn af-btn-sm"
                    onClick={() => setHistoric(null)}
                  >
                    Return to latest version
                  </button>
                </div>
              )}
              <WorkflowSnapshot key={current.id} version={current} />
            </TabsContent>
          </Tabs>
        ) : (
          <p role="status">Loading workflow…</p>
        )
      ) : (
        <WorkflowList
          agentId={agentId}
          agentName={agent.name}
          page={page}
          onPageChange={setPage}
          onOpen={(workflowId) => {
            setHistoric(null);
            void setView("overview");
            setVersionPage(1);
            void setRunPage(null);
            void setSelected(workflowId);
          }}
        />
      )}
      <ConfirmationDialog
        open={discard}
        onOpenChange={setDiscard}
        title="Discard unsaved changes?"
        description="Saved versions keep their existing steps and outputs."
        confirmLabel="Discard changes"
        variant="destructive"
        onConfirm={closeEditor}
      />
      <ConfirmationDialog
        open={archive}
        onOpenChange={setArchive}
        title="Archive workflow?"
        description="Saved versions remain available to inspect."
        confirmLabel="Archive workflow"
        isPending={actions.archive.isPending}
        onConfirm={async () => {
          if (!detail.data) return;
          try {
            await actions.archive.mutateAsync({
              workflowId: selected,
              revision: detail.data.revision,
            });
            setArchive(false);
          } catch (failure) {
            setError(errorMessage(failure));
            setArchive(false);
          }
        }}
      />
    </div>
  );
}
