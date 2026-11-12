"use client";

import { Archive, Copy, MoreHorizontal, PlayCircle, Plus } from "lucide-react";
import { parseAsString, useQueryState } from "nuqs";
import { useState } from "react";
import { toast } from "sonner";

import { AppErrorState } from "@/components/app-error-state";
import { ConfirmationDialog } from "@/components/confirmation-dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { getErrorDisplay } from "@/shared/api/error/get-error-display";

import { useLatestWorkflowRun } from "../hooks/use-workflow-runs";
import {
  useWorkflow,
  useWorkflowActions,
  useWorkflowCapabilities,
} from "../hooks/use-workflows";
import { type WorkflowVersion } from "../schemas";
import {
  workflowFilterParser,
  workflowPageParser,
  workflowsTabParser,
  workflowViewParser,
} from "../url-state";
import { WorkflowApprovalInbox } from "./workflow-approval-inbox";
import {
  WorkflowEditorDialog,
  type WorkflowEditorTarget,
} from "./workflow-editor-dialog";
import { WorkflowHistory } from "./workflow-history";
import { WorkflowList } from "./workflow-list";
import { WorkflowRunDialog } from "./workflow-run-dialog";
import { WorkflowRunList } from "./workflow-run-list";
import { WorkflowRunDetail } from "./workflow-runs";
import { WorkflowSnapshot } from "./workflow-snapshot";

const pill =
  "h-9 flex-none rounded-full px-4 data-active:border-[var(--line-strong)] data-active:bg-[var(--bg-elev)] data-active:text-[var(--ink)] data-active:shadow-sm";
const line =
  "h-full flex-none border-0 px-4 group-data-horizontal/tabs:after:bottom-[-1px]";
const urlText = parseAsString
  .withDefault("")
  .withOptions({ history: "push", scroll: false });

/**
 * The Organization's Workflows: every saved workflow and the runs the viewer can see.
 * Workflows are created, edited and started here; a run names the Agent that runs it.
 */
export function WorkflowsPage({ organizationId }: { organizationId: string }) {
  const [selected, setSelected] = useQueryState("workflow", urlText);
  const [runId, setRunId] = useQueryState("workflowRun", urlText);
  const [landingTab, setLandingTab] = useQueryState("workflowsTab", workflowsTabParser);
  const [view, setView] = useQueryState("workflowView", workflowViewParser);
  const [page, setPage] = useQueryState("workflowPage", workflowPageParser);
  const [filter, setFilter] = useQueryState("workflowFilter", workflowFilterParser);
  const [recentPage, setRecentPage] = useQueryState("workflowRunPage", workflowPageParser);
  const [versionPage, setVersionPage] = useQueryState("workflowVersionPage", workflowPageParser);
  // The Agent a link asked to run as, such as "Run a workflow" on an Agent's page.
  const [preferredAgent] = useQueryState("agent", parseAsString.withDefault(""));
  const capabilities = useWorkflowCapabilities();
  const detail = useWorkflow(selected);
  const actions = useWorkflowActions();
  const latestRun = useLatestWorkflowRun();
  const [editor, setEditor] = useState<WorkflowEditorTarget | null>(null);
  const [running, setRunning] = useState<{
    workflowId: string;
    version?: WorkflowVersion;
  } | null>(null);
  const [archiving, setArchiving] = useState<{
    id: string;
    name: string;
    revision: number;
  } | null>(null);
  const [historic, setHistoric] = useState<WorkflowVersion | null>(null);
  const canCreate = capabilities.data?.authoring === true;
  const canRun = capabilities.data?.execution === true;

  const openRun = (id: string) => {
    setRunning(null);
    setHistoric(null);
    void setSelected("");
    void setView(null);
    void setRunId(id);
  };
  const openWorkflow = (id: string) => {
    setHistoric(null);
    void setVersionPage(1);
    void setView("overview");
    void setRunId("");
    void setSelected(id);
  };
  const toLanding = (tab: "runs" | "workflows") => {
    setHistoric(null);
    void setView(null);
    void setRunId("");
    void setSelected("");
    void setLandingTab(tab);
  };
  const openLatestRun = async (workflowId: string) => {
    try {
      const run = await latestRun(workflowId);
      if (run) openRun(run.id);
      else toast.info("This workflow has no runs you can see yet.");
    } catch (failure) {
      toast.error(
        getErrorDisplay(failure, {
          title: "",
          description: "The latest run could not be loaded.",
        }).description,
      );
    }
  };

  // A failed refresh keeps what is on screen, including an open draft.
  if (capabilities.error && !capabilities.data)
    return (
      <AppErrorState
        error={capabilities.error}
        title="We couldn’t load workflows"
        onRetry={() => void capabilities.refetch()}
      />
    );
  if (selected && detail.error)
    return (
      <AppErrorState
        error={detail.error}
        title="We couldn’t load this workflow"
        onRetry={() => void detail.refetch()}
      />
    );

  const current = historic ?? detail.data?.version;
  const dialogs = (
    <>
      {editor && (
        <WorkflowEditorDialog
          target={editor}
          onClose={() => setEditor(null)}
          onSaved={(workflow) => {
            setEditor(null);
            // A new workflow, or a copy, opens so its author can check and run it.
            if (editor.mode !== "edit") openWorkflow(workflow.id);
            else setHistoric(null);
          }}
        />
      )}
      {running && (
        <WorkflowRunDialog
          workflowId={running.workflowId}
          version={running.version}
          preferredAgentId={preferredAgent || undefined}
          onClose={() => setRunning(null)}
          onStarted={(run) => openRun(run.id)}
        />
      )}
      <ConfirmationDialog
        open={archiving !== null}
        onOpenChange={(open) => !open && setArchiving(null)}
        title={`Archive ${archiving?.name ?? "workflow"}?`}
        description="It can no longer be run or edited. Its saved versions and past runs stay readable."
        confirmLabel="Archive workflow"
        variant="destructive"
        isPending={actions.archive.isPending}
        onConfirm={async () => {
          if (!archiving) return;
          try {
            await actions.archive.mutateAsync({
              workflowId: archiving.id,
              revision: archiving.revision,
            });
          } catch (failure) {
            toast.error(
              getErrorDisplay(failure, {
                title: "",
                description: "The workflow could not be archived. Refresh and try again.",
              }).description,
            );
          }
          setArchiving(null);
        }}
      />
    </>
  );

  if (runId)
    return (
      <div style={{ color: "var(--ink)" }}>
        <nav
          aria-label="Workflow navigation"
          className="flex flex-wrap items-center gap-2 text-sm text-[var(--ink-3)]"
        >
          <button
            type="button"
            className="hover:text-[var(--ink)]"
            aria-label="All workflows"
            onClick={() => toLanding("runs")}
          >
            Workflows
          </button>
          <span aria-hidden="true">/</span>
          <span aria-current="page" className="text-[var(--ink)]">
            Run detail
          </span>
        </nav>
        <WorkflowRunDetail
          organizationId={organizationId}
          runId={runId}
          onOpenRun={openRun}
        />
        {dialogs}
      </div>
    );

  if (selected)
    return (
      <div style={{ color: "var(--ink)" }}>
        <nav
          aria-label="Workflow navigation"
          className="flex flex-wrap items-center gap-2 text-sm text-[var(--ink-3)]"
        >
          <button
            type="button"
            className="hover:text-[var(--ink)]"
            aria-label="All workflows"
            onClick={() => toLanding("workflows")}
          >
            Workflows
          </button>
          <span aria-hidden="true">/</span>
          <span aria-current="page" className="max-w-60 truncate text-[var(--ink)]">
            {detail.data?.version.draft.name ?? "Workflow"}
          </span>
        </nav>
        <div className="my-6 flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-3xl font-semibold tracking-tight">
              {current?.draft.name || "Workflow"}
            </h1>
            <p className="mt-2 text-sm text-[var(--ink-3)]">
              Saved v{current?.number ?? "…"}
              {detail.data?.archivedAt ? " · Archived" : ""}
              {detail.data?.createdBy?.name
                ? ` · Created by ${detail.data.createdBy.name}`
                : ""}
            </p>
          </div>
          {detail.data && (
            <div className="flex flex-wrap gap-2">
              {detail.data.allowedActions.includes("save_version") && (
                <button
                  type="button"
                  className="af-btn"
                  onClick={() => setEditor({ mode: "edit", workflowId: detail.data.id })}
                >
                  {historic && historic.number !== detail.data.version.number
                    ? "Edit latest version"
                    : "Edit workflow"}
                </button>
              )}
              <button
                type="button"
                className="af-btn af-btn-primary"
                disabled={!canRun || !detail.data.executionAvailable}
                onClick={() =>
                  setRunning({
                    workflowId: detail.data.id,
                    version: historic ?? undefined,
                  })
                }
              >
                Run workflow
              </button>
              {(canCreate || detail.data.allowedActions.includes("archive")) && (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <button
                      type="button"
                      className="af-btn af-btn-icon"
                      aria-label="Workflow actions"
                    >
                      <MoreHorizontal size={18} />
                    </button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    {canCreate && (
                      <DropdownMenuItem
                        onSelect={() =>
                          setEditor({ mode: "duplicate", workflowId: detail.data.id })
                        }
                      >
                        <Copy size={15} /> Duplicate
                      </DropdownMenuItem>
                    )}
                    {detail.data.allowedActions.includes("archive") && (
                      <DropdownMenuItem
                        variant="destructive"
                        onSelect={() =>
                          setArchiving({
                            id: detail.data.id,
                            name: detail.data.version.draft.name,
                            revision: detail.data.revision,
                          })
                        }
                      >
                        <Archive size={15} /> Archive workflow
                      </DropdownMenuItem>
                    )}
                  </DropdownMenuContent>
                </DropdownMenu>
              )}
            </div>
          )}
        </div>
        {detail.data && current ? (
          <Tabs
            value={view}
            onValueChange={(value) => {
              if (value !== "overview" && value !== "history" && value !== "runs") return;
              void setView(value);
              if (value !== "history") setHistoric(null);
            }}
            className="gap-6"
          >
            <TabsList
              variant="line"
              aria-label="Workflow views"
              className="w-full justify-start border-b border-[var(--line)] p-0"
            >
              <TabsTrigger value="overview" className={line}>
                Overview
              </TabsTrigger>
              <TabsTrigger value="runs" className={line}>
                Runs
              </TabsTrigger>
              <TabsTrigger value="history" className={line}>
                Version history
              </TabsTrigger>
            </TabsList>
            <TabsContent value="runs">
              <WorkflowRunList
                title="Runs of this workflow"
                filters={{ workflowId: detail.data.id }}
                page={recentPage}
                onPageChange={setRecentPage}
                onOpen={(run) => openRun(run.id)}
                empty={
                  <p className="af-card p-6 text-sm text-[var(--ink-3)]">
                    No runs you can see yet. Runs appear here for the agents you have
                    access to.
                  </p>
                }
              />
            </TabsContent>
            <TabsContent value="history">
              <WorkflowHistory
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
            <TabsContent value="overview">
              {historic && historic.number !== detail.data.version.number && (
                <div className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-xl bg-[var(--accent-soft)] px-5 py-3 text-sm">
                  <p>
                    Viewing saved v{historic.number}. The latest version is v
                    {detail.data.version.number}.
                  </p>
                  <button
                    type="button"
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
        )}
        {dialogs}
      </div>
    );

  return (
    <div style={{ color: "var(--ink)" }}>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div className="max-w-2xl">
          <h1 className="text-3xl font-semibold tracking-tight">Workflows</h1>
          <p className="mt-2 text-[var(--ink-3)]">
            Reusable plans your agents run step by step, pausing for your approval
            where a command needs it.
          </p>
        </div>
        {canCreate && (
          <button
            type="button"
            className="af-btn af-btn-primary"
            onClick={() => setEditor({ mode: "create" })}
          >
            <Plus size={16} aria-hidden="true" /> New workflow
          </button>
        )}
      </div>
      {capabilities.data?.authoring === false && (
        <p className="mb-6 text-sm">
          Workflow authoring is disabled for this installation.
        </p>
      )}
      <Tabs
        value={landingTab}
        onValueChange={(value) => {
          if (value === "runs" || value === "workflows") void setLandingTab(value);
        }}
        className="gap-6"
      >
        <TabsList
          aria-label="Workflows views"
          className="gap-1 bg-transparent p-0 group-data-horizontal/tabs:h-auto"
        >
          <TabsTrigger value="runs" className={pill}>
            Runs
          </TabsTrigger>
          <TabsTrigger value="workflows" className={pill}>
            Workflows
          </TabsTrigger>
        </TabsList>
        <TabsContent value="runs">
          <WorkflowApprovalInbox onOpen={(run) => openRun(run.id)} />
          <WorkflowRunList
            title="Active"
            filters={{ status: "active", pageSize: 50 }}
            page={1}
            onOpen={(run) => openRun(run.id)}
          />
          <WorkflowRunList
            title="Recent"
            filters={{ status: "settled" }}
            page={recentPage}
            onPageChange={setRecentPage}
            onOpen={(run) => openRun(run.id)}
            empty={
              <div className="flex flex-col items-center pt-12 pb-12 text-center">
                <span className="mb-4 flex size-14 items-center justify-center rounded-2xl bg-[var(--bg-soft)] text-[var(--ink-3)]">
                  <PlayCircle aria-hidden="true" size={24} />
                </span>
                <h2 className="text-lg font-semibold">No finished runs yet</h2>
                <p className="mt-2 max-w-sm text-sm text-[var(--ink-3)]">
                  Runs appear here once they end. Start one from a{" "}
                  <button
                    type="button"
                    className="underline hover:text-[var(--ink)]"
                    onClick={() => void setLandingTab("workflows")}
                  >
                    saved workflow
                  </button>
                  .
                </p>
              </div>
            }
          />
        </TabsContent>
        <TabsContent value="workflows">
          <WorkflowList
            page={page}
            onPageChange={setPage}
            filter={filter}
            onFilterChange={(next) => {
              void setPage(1);
              void setFilter(next);
            }}
            canCreate={canCreate}
            canRun={canRun}
            onOpen={(workflow) => openWorkflow(workflow.id)}
            onRun={(workflow) => setRunning({ workflowId: workflow.id })}
            onEdit={(workflow) => setEditor({ mode: "edit", workflowId: workflow.id })}
            onDuplicate={(workflow) =>
              setEditor({ mode: "duplicate", workflowId: workflow.id })
            }
            onOpenLatestRun={(workflow) => void openLatestRun(workflow.id)}
            onArchive={(workflow) =>
              setArchiving({
                id: workflow.id,
                name: workflow.version.name,
                revision: workflow.revision,
              })
            }
          />
        </TabsContent>
      </Tabs>
      {dialogs}
    </div>
  );
}
