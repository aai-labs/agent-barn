"use client";

import { useRef, useState } from "react";

import { AppErrorState } from "@/components/app-error-state";
import { ConfirmationDialog } from "@/components/confirmation-dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { useAgents } from "@/features/agents/hooks/use-agents";
import { ApiError } from "@/shared/api/error/errors";

import { useWorkflow, useWorkflowActions } from "../hooks/use-workflows";
import {
  WorkflowDraftSchema,
  type Workflow,
  type WorkflowDraft,
} from "../schemas";
import { changedByOthers, foldStepOutputs } from "../utils";
import {
  workflowApiProblems,
  workflowProblems,
  type WorkflowProblem,
} from "../validation";
import { emptyDraft, WorkflowEditor } from "./workflow-editor";
import { WorkflowSaveAlert } from "./workflow-save-alert";

/** What the editor opens on: a new workflow, a copy of a saved one, or a saved one's next version. */
export type WorkflowEditorTarget =
  | { mode: "create" }
  | { mode: "duplicate"; workflowId: string }
  | { mode: "edit"; workflowId: string };

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

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

/** The draft as the API would store it, so an untouched form compares equal to what was saved. */
function normalized(draft: WorkflowDraft): WorkflowDraft {
  const parsed = WorkflowDraftSchema.safeParse(draft);
  return parsed.success ? parsed.data : draft;
}

function EditorForm({
  target,
  source,
  onClose,
  onSaved,
}: {
  target: WorkflowEditorTarget;
  /** The saved workflow being edited or copied. */
  source: Workflow | null;
  onClose: () => void;
  onSaved: (workflow: Workflow) => void;
}) {
  const editing = target.mode === "edit" && source !== null;
  const actions = useWorkflowActions();
  // Any Agent the author can see may be the default; it only preselects "Run as".
  const { agents } = useAgents();
  const detail = useWorkflow(editing ? source.id : "");
  const [initial] = useState<WorkflowDraft>(() => {
    if (!source) return emptyDraft("");
    const folded = foldStepOutputs(structuredClone(source.version.draft));
    return target.mode === "duplicate"
      ? { ...folded, name: `${folded.name} (copy)`.slice(0, 200) }
      : folded;
  });
  const [draft, setDraft] = useState(initial);
  const [initialAgent] = useState(source?.defaultAgentId ?? null);
  const [defaultAgentId, setDefaultAgentId] = useState(initialAgent);
  // What another save changed is shown against the draft this edit started from.
  const [base, setBase] = useState(source?.version.draft ?? initial);
  const [revision, setRevision] = useState(source?.revision ?? 0);
  const [problems, setProblems] = useState<WorkflowProblem[]>([]);
  const [attempted, setAttempted] = useState(false);
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState(false);
  const [notice, setNotice] = useState<string[]>([]);
  const [discard, setDiscard] = useState(false);
  const body = useRef<HTMLDivElement>(null);
  const pending = actions.save.isPending || actions.setDefaultAgent.isPending;
  const draftChanged = !same(normalized(draft), normalized(initial));
  const agentChanged = defaultAgentId !== initialAgent;
  const unsaved = draftChanged || agentChanged;
  const maySave = !editing || source.allowedActions.includes("save_version");
  const reveal = (section: string) =>
    body.current
      ?.querySelector(`[data-section="${section}"]`)
      ?.scrollIntoView({ block: "center" });
  const close = () => (unsaved && !pending ? setDiscard(true) : onClose());

  async function save() {
    setAttempted(true);
    const validated = WorkflowDraftSchema.safeParse(draft);
    if (!validated.success) {
      const issues = workflowProblems(validated.error.issues, draft);
      setProblems(issues);
      setError("Review these fields before saving. Your edits are retained.");
      reveal(issues[0].section);
      return;
    }
    try {
      let saved: Workflow | null = null;
      if (!editing) {
        saved = await actions.save.mutateAsync({
          draft: validated.data,
          defaultAgentId,
        });
      } else {
        let current = revision;
        // A new version only when the plan itself changed; the default Agent is not versioned.
        if (draftChanged) {
          saved = await actions.save.mutateAsync({
            draft: validated.data,
            workflowId: source.id,
            revision: current,
          });
          current = saved.revision;
          setRevision(current);
        }
        if (agentChanged)
          saved = await actions.setDefaultAgent.mutateAsync({
            workflowId: source.id,
            revision: current,
            defaultAgentId,
          });
      }
      if (saved) onSaved(saved);
      else onClose();
    } catch (failure) {
      const issues = workflowApiProblems(failure, draft);
      setProblems(issues);
      setError(
        issues.length
          ? "Review these fields before saving. Your edits are retained."
          : errorMessage(failure),
      );
      setConflict(failure instanceof ApiError && failure.status === 409);
      if (issues.length) reveal(issues[0].section);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && close()}>
      <DialogContent
        aria-describedby={undefined}
        className="flex max-h-[92vh] w-[calc(100vw-2rem)] max-w-3xl flex-col gap-0 overflow-hidden p-0 sm:rounded-3xl"
        style={{ background: "var(--bg)", color: "var(--ink)" }}
        onInteractOutside={(event) => event.preventDefault()}
      >
        <header className="px-6 pt-6 pb-3">
          <DialogDescription className="text-[11px] font-semibold uppercase tracking-widest text-[var(--ink-3)]">
            {editing
              ? `Edit workflow · ${source.version.draft.name}`
              : target.mode === "duplicate"
                ? "Duplicate workflow"
                : "New workflow"}
          </DialogDescription>
          <DialogTitle className="mt-1 text-2xl font-semibold tracking-tight">
            {editing ? "Refine the workflow" : "Design a reusable workflow"}
          </DialogTitle>
        </header>
        {/* The dialog sets only a max height, so the viewport sizes by flex, not 100%. */}
        <ScrollArea className="flex min-h-0 flex-1 flex-col [&>[data-slot=scroll-area-viewport]]:min-h-0 [&>[data-slot=scroll-area-viewport]]:flex-1">
          <div ref={body} className="px-6 pb-6">
            {error && (
              <WorkflowSaveAlert
                message={error}
                problems={problems}
                onSelect={reveal}
                onLoadCurrent={
                  conflict && editing
                    ? async () => {
                        const latest = await detail.refetch();
                        if (!latest.data) return;
                        setNotice(changedByOthers(base, latest.data.version.draft));
                        setBase(latest.data.version.draft);
                        setRevision(latest.data.revision);
                        setConflict(false);
                        setError("");
                      }
                    : undefined
                }
              />
            )}
            {editing && !error && notice.length > 0 && (
              <div role="status" className="af-card mb-5 p-5 text-sm">
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
            <WorkflowEditor
              draft={draft}
              onChange={(next) => {
                setDraft(next);
                setProblems([]);
                setError("");
              }}
              disabled={!maySave || pending}
              problems={problems}
              revealed={attempted}
              agents={agents.map(({ id, name }) => ({ id, name }))}
              defaultAgentId={defaultAgentId}
              onDefaultAgentChange={setDefaultAgentId}
            />
          </div>
        </ScrollArea>
        <footer className="flex items-center justify-between gap-3 border-t border-[var(--line)] bg-[var(--bg-soft)] px-6 py-4">
          <button type="button" className="af-btn af-btn-ghost" disabled={pending} onClick={close}>
            Cancel
          </button>
          <button
            type="button"
            className="af-btn af-btn-primary"
            disabled={!maySave || pending || draft.steps.length === 0}
            onClick={() => void save()}
          >
            {pending ? "Saving…" : editing ? "Save changes" : "Save workflow"}
          </button>
        </footer>
        <ConfirmationDialog
          open={discard}
          onOpenChange={setDiscard}
          title="Discard unsaved changes?"
          description="Saved versions keep their existing steps."
          confirmLabel="Discard changes"
          variant="destructive"
          onConfirm={onClose}
        />
      </DialogContent>
    </Dialog>
  );
}

/**
 * The workflow editor, opened over the Workflows page. Editing or copying a saved
 * workflow waits for its latest version before the form opens.
 */
export function WorkflowEditorDialog({
  target,
  onClose,
  onSaved,
}: {
  target: WorkflowEditorTarget;
  onClose: () => void;
  onSaved: (workflow: Workflow) => void;
}) {
  const sourceId = target.mode === "create" ? "" : target.workflowId;
  const source = useWorkflow(sourceId);
  if (sourceId && !source.data)
    return (
      <Dialog open onOpenChange={(open) => !open && onClose()}>
        <DialogContent aria-describedby={undefined} style={{ background: "var(--bg)", color: "var(--ink)" }}>
          <DialogTitle>Workflow</DialogTitle>
          {source.error ? (
            <AppErrorState
              error={source.error}
              title="We couldn’t load this workflow"
              onRetry={() => void source.refetch()}
            />
          ) : (
            <p role="status">Loading workflow…</p>
          )}
        </DialogContent>
      </Dialog>
    );
  return (
    <EditorForm
      // A different target is a different form: its draft must not carry over.
      key={`${target.mode}:${sourceId}`}
      target={target}
      source={source.data ?? null}
      onClose={onClose}
      onSaved={onSaved}
    />
  );
}
