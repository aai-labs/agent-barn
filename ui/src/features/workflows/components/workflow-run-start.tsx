"use client";

import { useState } from "react";
import { AlertCircleIcon } from "@/components/icons";
import { getErrorDisplay } from "@/shared/api/error/get-error-display";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import type { WorkflowInputValue } from "../run-schemas";
import { WorkflowFileInput } from "./workflow-file-input";
import type { WorkflowVersion } from "../schemas";
import { useWorkflowRunActions } from "../hooks/use-workflow-runs";
import {
  RunPageHeader,
  RunRow,
  StatusBadge,
  StepRail,
} from "./workflow-run-parts";

export function WorkflowRunStart({
  agentId,
  agent,
  workflowId,
  version,
  onStarted,
  onBack,
}: {
  agentId: string;
  agent: { id: string; name: string };
  workflowId: string;
  version: WorkflowVersion;
  onStarted: (id: string) => void;
  onBack: () => void;
}) {
  const actions = useWorkflowRunActions(agentId);
  const [values, setValues] = useState<Record<string, WorkflowInputValue>>(() =>
    Object.fromEntries(
      version.draft.inputs
        .filter((input) => input.type === "boolean")
        .map((input) => [input.key, false]),
    ),
  );
  // Retain this identity through transport retries. Edits create a fresh request identity.
  const [requestId, setRequestId] = useState(() => crypto.randomUUID());
  const setValue = (key: string, value: WorkflowInputValue) => {
    setValues((previous) => ({ ...previous, [key]: value }));
    setRequestId(crypto.randomUUID());
  };
  const [uploads, setUploads] = useState<Record<string, boolean>>({});
  const uploading = Object.values(uploads).some(Boolean);
  const [validation, setValidation] = useState("");
  return (
    <>
      <RunPageHeader
        eyebrow={`Workflow · v${version.number}`}
        title={version.draft.name}
        badge={<StatusBadge tone="ok">Saved v{version.number}</StatusBadge>}
        agent={agent}
      />
      <div className="grid gap-8 md:grid-cols-[minmax(200px,260px)_minmax(0,1fr)]">
        <StepRail
          runState="QUEUED"
          steps={version.draft.steps.map((step) => ({
            id: step.id,
            name: step.name,
            state: "PENDING" as const,
          }))}
        />
        <section
          className="rounded-2xl border border-[var(--line)] bg-[var(--bg-elev)] p-6 space-y-6"
          aria-label="Run inputs"
        >
          <div>
            <h3 className="text-lg font-semibold">Start a run</h3>
            <p className="mt-2 text-sm text-[var(--ink-3)]">
              This run uses version {version.number}. Review the inputs before
              starting.
            </p>
          </div>
          <form
            className="space-y-6"
            onSubmit={async (event) => {
              event.preventDefault();
              if (uploading) return;
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
                inputs[input.key] =
                  input.type === "number" ? Number(value) : value;
                if (
                  input.type === "number" &&
                  !Number.isFinite(inputs[input.key])
                ) {
                  setValidation(`${input.label} must be a number`);
                  return;
                }
              }
              setValidation("");
              try {
                const run = await actions.start.mutateAsync({
                  workflowId,
                  versionId: version.id,
                  clientRequestId: requestId,
                  inputs,
                });
                onStarted(run.id);
              } catch {
                /* The inline error preserves inputs and request identity. */
              }
            }}
          >
            {version.draft.inputs.length === 0 && (
              <p>No inputs are required.</p>
            )}
            <div className="grid gap-6 lg:grid-cols-2">
              {version.draft.inputs.map((input) => (
                <div
                  key={input.key}
                  className={`space-y-2 ${["text", "file"].includes(input.type) ? "lg:col-span-2" : ""}`}
                >
                  <Label
                    htmlFor={`run-input-${input.key}`}
                    className="font-semibold"
                  >
                    {input.label}
                    {input.required ? " (required)" : " (optional)"}
                  </Label>
                  <p className="text-sm text-[var(--ink-3)]">
                    {input.description}
                  </p>
                  {input.type === "file" ? (
                    <WorkflowFileInput
                      id={`run-input-${input.key}`}
                      agentId={agentId}
                      label={input.label}
                      value={values[input.key]}
                      disabled={actions.start.isPending}
                      onUploadingChange={(busy) =>
                        setUploads((previous) => ({
                          ...previous,
                          [input.key]: busy,
                        }))
                      }
                      onChange={(value) => setValue(input.key, value)}
                    />
                  ) : input.type === "boolean" ? (
                    <Checkbox
                      id={`run-input-${input.key}`}
                      checked={values[input.key] === true}
                      onCheckedChange={(checked) =>
                        setValue(input.key, checked === true)
                      }
                    />
                  ) : input.type === "number" ? (
                    <Input
                      id={`run-input-${input.key}`}
                      type={input.type === "number" ? "number" : "text"}
                      step="any"
                      required={input.required}
                      maxLength={16000}
                      value={String(values[input.key] ?? "")}
                      onChange={(event) =>
                        setValue(input.key, event.target.value)
                      }
                    />
                  ) : (
                    <Textarea
                      id={`run-input-${input.key}`}
                      required={input.required}
                      maxLength={16000}
                      className="min-h-24 rounded-xl border-[var(--line-strong)] bg-[var(--bg-elev)] px-3 py-2.5"
                      value={String(values[input.key] ?? "")}
                      onChange={(event) =>
                        setValue(input.key, event.target.value)
                      }
                    />
                  )}
                </div>
              ))}
            </div>
            {validation && <p role="alert">{validation}</p>}
            {actions.start.error && (
              <div
                role="alert"
                className="flex items-start gap-3 rounded-xl border px-4 py-3.5"
                style={{
                  background: "var(--err-soft)",
                  borderColor:
                    "color-mix(in srgb, var(--err) 30%, transparent)",
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
            <div>
              <RunRow label="Workflow" value={version.draft.name} />
              <RunRow label="Saved version" value={`v${version.number}`} />
              <RunRow
                label="Steps"
                value={`${version.draft.steps.length} to run in order`}
              />
            </div>
            <div className="flex justify-end gap-3 pt-2">
              <button className="af-btn" type="button" onClick={onBack}>
                Cancel
              </button>
              <button
                className="af-btn af-btn-primary"
                disabled={actions.start.isPending || uploading}
                type="submit"
              >
                {actions.start.isPending ? "Starting…" : "Start run →"}
              </button>
            </div>
          </form>
        </section>
      </div>
    </>
  );
}
