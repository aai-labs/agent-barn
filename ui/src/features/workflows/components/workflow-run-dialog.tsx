"use client";

import { ChevronRight, Hourglass } from "lucide-react";
import { useState } from "react";

import { AppErrorState } from "@/components/app-error-state";
import { AlertCircleIcon } from "@/components/icons";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useAgents } from "@/features/agents/hooks/use-agents";
import { canAgent } from "@/features/agents/utils";
import { getErrorDisplay } from "@/shared/api/error/get-error-display";

import { useWorkflowRunActions } from "../hooks/use-workflow-runs";
import { useWorkflow } from "../hooks/use-workflows";
import type { WorkflowInputValue, WorkflowRun } from "../run-schemas";
import type { Workflow, WorkflowVersion } from "../schemas";
import { inputHelp } from "../utils";
import { AgentPillPicker } from "./agent-pill-picker";
import { WorkflowFileInput } from "./workflow-file-input";

function RunForm({
  workflow,
  version,
  preferredAgentId,
  onClose,
  onStarted,
}: {
  workflow: Workflow;
  version: WorkflowVersion;
  preferredAgentId?: string;
  onClose: () => void;
  onStarted: (run: WorkflowRun) => void;
}) {
  const actions = useWorkflowRunActions();
  const { agents, isLoading, error: agentsError, refetch } = useAgents();
  // A run needs agent.update on a running Agent; the server checks again on start.
  const runnable = agents.filter(
    (agent) => agent.status === "RUNNING" && canAgent(agent, "agent.update"),
  );
  const offered = (id?: string | null) =>
    id && runnable.some((agent) => agent.id === id) ? id : null;
  // Until someone chooses, the Agent the link named wins, then the workflow's default.
  const [chosen, setChosen] = useState<string | null | undefined>(undefined);
  const agentId =
    chosen !== undefined
      ? offered(chosen)
      : (offered(preferredAgentId) ?? offered(workflow.defaultAgentId));
  const [title, setTitle] = useState("");
  const [values, setValues] = useState<Record<string, WorkflowInputValue>>(() =>
    Object.fromEntries(
      version.draft.inputs
        .filter((input) => input.type === "boolean")
        .map((input) => [input.key, false]),
    ),
  );
  // Retain this identity through transport retries. Edits create a fresh request identity.
  const [requestId, setRequestId] = useState(() => crypto.randomUUID());
  const fresh = () => setRequestId(crypto.randomUUID());
  const setValue = (key: string, value: WorkflowInputValue) => {
    setValues((previous) => ({ ...previous, [key]: value }));
    fresh();
  };
  const [uploads, setUploads] = useState<Record<string, boolean>>({});
  const uploading = Object.values(uploads).some(Boolean);
  const [validation, setValidation] = useState("");
  const fileKeys = version.draft.inputs
    .filter((input) => input.type === "file")
    .map((input) => input.key);
  const chooseAgent = (id: string) => {
    if (id === agentId) return;
    setChosen(id);
    // Files belong to one Agent, so a file picked for another cannot be used.
    setValues((previous) =>
      Object.fromEntries(
        Object.entries(previous).filter(([key]) => !fileKeys.includes(key)),
      ),
    );
    setUploads({});
    fresh();
  };
  const pending = actions.start.isPending;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (uploading || pending) return;
    if (!agentId) {
      setValidation("Choose the agent that should run this workflow");
      return;
    }
    const inputs: Record<string, WorkflowInputValue> = {};
    for (const input of version.draft.inputs) {
      const value = values[input.key];
      if (value === undefined || value === "") {
        if (input.required) {
          setValidation(`${input.label} is required`);
          return;
        }
        continue;
      }
      inputs[input.key] = input.type === "number" ? Number(value) : value;
      if (input.type === "number" && !Number.isFinite(inputs[input.key])) {
        setValidation(`${input.label} must be a number`);
        return;
      }
    }
    setValidation("");
    try {
      onStarted(
        await actions.start.mutateAsync({
          workflowId: workflow.id,
          agentId,
          versionId: version.id,
          title,
          clientRequestId: requestId,
          inputs,
        }),
      );
    } catch {
      /* The inline error preserves inputs and request identity. */
    }
  }

  return (
    <form className="flex min-h-0 flex-1 flex-col" onSubmit={(event) => void submit(event)}>
      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-6 pb-6">
        <div className="space-y-1.5">
          <Label htmlFor="workflow-run-title" className="font-semibold">
            Name this run
          </Label>
          <Input
            id="workflow-run-title"
            maxLength={200}
            placeholder={`Run of ${version.draft.name}`}
            value={title}
            onChange={(event) => {
              setTitle(event.target.value);
              fresh();
            }}
          />
        </div>

        <div>
          <p id="workflow-run-as" className="mb-1.5 text-sm font-semibold">
            Run as
          </p>
          {agentsError ? (
            <AppErrorState
              error={agentsError}
              title="We couldn’t load your agents"
              onRetry={() => void refetch()}
            />
          ) : isLoading ? (
            <p role="status" className="text-sm text-[var(--ink-3)]">
              Loading agents…
            </p>
          ) : runnable.length === 0 ? (
            <p className="text-sm text-[var(--ink-3)]">
              No running agent you can update. Start an agent, then run this workflow.
            </p>
          ) : (
            <AgentPillPicker
              labelledBy="workflow-run-as"
              agents={runnable}
              value={agentId}
              onChange={(id) => id && chooseAgent(id)}
              // An upload belongs to the Agent it started on, so the choice waits for it.
              disabled={pending || uploading}
            />
          )}
        </div>

        <section
          aria-label="This run will"
          className="rounded-2xl border border-[var(--line)] bg-[var(--bg-soft)] p-4"
        >
          <h3 className="mb-2 text-sm font-semibold">This run will</h3>
          <ol className="flex flex-wrap items-center gap-x-1 gap-y-2">
            {version.draft.steps.map((step, index) => (
              <li key={step.id} className="flex items-center gap-1 text-xs">
                <span className="rounded-full border border-[var(--line)] bg-[var(--bg-elev)] px-2.5 py-1">
                  {step.name}
                </span>
                {index < version.draft.steps.length - 1 && (
                  <ChevronRight size={12} aria-hidden="true" className="text-[var(--ink-4)]" />
                )}
              </li>
            ))}
          </ol>
          <p className="mt-3 flex items-center gap-2 text-xs text-[var(--ink-3)]">
            <Hourglass size={13} aria-hidden="true" />
            Uses saved version {version.number}. It pauses for your approval when the agent
            asks to run a command that needs it.
          </p>
        </section>

        {version.draft.inputs.length > 0 && (
          <div className="space-y-5">
            {version.draft.inputs.map((input) => (
              <div key={input.key} className="space-y-1.5">
                <Label htmlFor={`run-input-${input.key}`} className="font-semibold">
                  {input.label}
                  {input.required ? " (required)" : " (optional)"}
                </Label>
                {inputHelp(input) && (
                  <p className="text-sm text-[var(--ink-3)]">{inputHelp(input)}</p>
                )}
                {input.type === "file" ? (
                  agentId ? (
                    <WorkflowFileInput
                      // Another Agent has other files: start the picker over.
                      key={agentId}
                      id={`run-input-${input.key}`}
                      agentId={agentId}
                      label={input.label}
                      value={values[input.key]}
                      disabled={pending}
                      onUploadingChange={(busy) =>
                        setUploads((previous) => ({ ...previous, [input.key]: busy }))
                      }
                      onChange={(value) => setValue(input.key, value)}
                    />
                  ) : (
                    <p className="rounded-xl border border-dashed border-[var(--line-strong)] px-3 py-2.5 text-sm text-[var(--ink-3)]">
                      Choose an agent under “Run as” to attach one of its files.
                    </p>
                  )
                ) : input.type === "boolean" ? (
                  <Checkbox
                    id={`run-input-${input.key}`}
                    checked={values[input.key] === true}
                    onCheckedChange={(checked) => setValue(input.key, checked === true)}
                  />
                ) : input.type === "number" ? (
                  <Input
                    id={`run-input-${input.key}`}
                    type="number"
                    step="any"
                    required={input.required}
                    value={String(values[input.key] ?? "")}
                    onChange={(event) => setValue(input.key, event.target.value)}
                  />
                ) : (
                  <Textarea
                    id={`run-input-${input.key}`}
                    required={input.required}
                    maxLength={16000}
                    className="min-h-20 rounded-xl border-[var(--line-strong)] bg-[var(--bg-elev)] px-3 py-2.5"
                    value={String(values[input.key] ?? "")}
                    onChange={(event) => setValue(input.key, event.target.value)}
                  />
                )}
              </div>
            ))}
          </div>
        )}
        {validation && (
          <p role="alert" className="text-sm" style={{ color: "var(--err)" }}>
            {validation}
          </p>
        )}
        {actions.start.error && (
          <div
            role="alert"
            className="flex items-start gap-3 rounded-xl border px-4 py-3.5"
            style={{
              background: "var(--err-soft)",
              borderColor: "color-mix(in srgb, var(--err) 30%, transparent)",
              color: "var(--err)",
            }}
          >
            <AlertCircleIcon size={15} className="mt-0.5 shrink-0" />
            <div className="text-sm">
              <p className="font-medium">
                The run could not be started. Your inputs are retained.
              </p>
              <p className="mt-0.5 text-[13px]">
                {
                  getErrorDisplay(actions.start.error, {
                    title: "",
                    description: "Check your connection and try again.",
                  }).description
                }
              </p>
            </div>
          </div>
        )}
      </div>
      <footer className="flex items-center justify-between gap-3 border-t border-[var(--line)] bg-[var(--bg-soft)] px-6 py-4">
        <button type="button" className="af-btn af-btn-ghost" disabled={pending} onClick={onClose}>
          Cancel
        </button>
        <button
          type="submit"
          className="af-btn af-btn-primary"
          disabled={pending || uploading || !agentId}
        >
          {pending ? "Starting…" : "Start run"}
        </button>
      </footer>
    </form>
  );
}

/**
 * Starts a run of a saved workflow on an Agent chosen here. It runs the latest version
 * unless an earlier `version` is given.
 */
export function WorkflowRunDialog({
  workflowId,
  version,
  preferredAgentId,
  onClose,
  onStarted,
}: {
  workflowId: string;
  /** An earlier saved version to run instead of the latest. */
  version?: WorkflowVersion;
  /** The Agent a link asked for, such as the Agent page this was opened from. */
  preferredAgentId?: string;
  onClose: () => void;
  onStarted: (run: WorkflowRun) => void;
}) {
  const workflow = useWorkflow(workflowId);
  const running = version ?? workflow.data?.version;
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        aria-describedby={undefined}
        className="flex max-h-[92vh] w-[calc(100vw-2rem)] max-w-xl flex-col gap-0 overflow-hidden p-0 sm:rounded-3xl"
        style={{ background: "var(--bg)", color: "var(--ink)" }}
      >
        <header className="px-6 pt-6 pb-4">
          <DialogDescription className="text-[11px] font-semibold uppercase tracking-widest text-[var(--ink-3)]">
            Run workflow
          </DialogDescription>
          <DialogTitle className="mt-1 text-2xl font-semibold tracking-tight">
            {running?.draft.name ?? "Workflow"}{" "}
            {running && (
              <span className="font-mono text-sm font-normal text-[var(--ink-3)]">
                v{running.number}
              </span>
            )}
          </DialogTitle>
        </header>
        {workflow.error ? (
          <div className="px-6 pb-6">
            <AppErrorState
              error={workflow.error}
              title="We couldn’t load this workflow"
              onRetry={() => void workflow.refetch()}
            />
          </div>
        ) : workflow.data && running ? (
          <RunForm
            key={running.id}
            workflow={workflow.data}
            version={running}
            preferredAgentId={preferredAgentId}
            onClose={onClose}
            onStarted={onStarted}
          />
        ) : (
          <p role="status" className="px-6 pb-6">
            Loading workflow…
          </p>
        )}
      </DialogContent>
    </Dialog>
  );
}
