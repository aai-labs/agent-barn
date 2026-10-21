"use client";

import { useCallback, useMemo, useState } from "react";

import { type WorkflowDraft, type WorkflowStep } from "../schemas";
import {
  stepField,
  workflowFieldErrors,
  type WorkflowProblem,
} from "../validation";
import { WorkflowField as Field } from "./workflow-field";
import { WorkflowInputsEditor } from "./workflow-inputs-editor";
import { WorkflowOutline } from "./workflow-outline";

export function emptyStep(): WorkflowStep {
  return {
    id: crypto.randomUUID(),
    name: "",
    goal: "",
    completionCriteria: "",
    artifactDescription: null,
    requiredCapabilities: ["reasoning"],
  };
}
export function emptyDraft(description: string): WorkflowDraft {
  return {
    schemaVersion: 1,
    name: "",
    description,
    steps: [emptyStep()],
    inputs: [],
    finalArtifactDescription: null,
    reviewDestination: "web",
  };
}
export function WorkflowEditor({
  draft,
  selected,
  onSelect,
  onChange,
  disabled,
  problems,
  revealed,
}: {
  draft: WorkflowDraft;
  selected: string;
  onSelect: (section: string) => void;
  onChange: (draft: WorkflowDraft) => void;
  disabled: boolean;
  /** Problems from the last save attempt, including server validation. */
  problems: WorkflowProblem[];
  /** After a save attempt every invalid field shows its message. */
  revealed: boolean;
}) {
  // Fields show live client validation once left (blurred) or after a save
  // attempt; the save summary still lists and links every problem.
  const [touched, setTouched] = useState<ReadonlySet<string>>(new Set());
  const fieldErrors = useMemo(() => workflowFieldErrors(draft), [draft]);
  const errorFor = (field: string) =>
    touched.has(field) || revealed
      ? (fieldErrors.get(field) ??
        problems.find((problem) => problem.field === field)?.message)
      : undefined;
  const touch = (field: string) =>
    setTouched((current) =>
      current.has(field) ? current : new Set(current).add(field),
    );
  const field = (id: string) => ({
    onBlur: () => touch(id),
    error: errorFor(id),
  });
  const focusUndo = useCallback((node: HTMLButtonElement | null) => {
    node?.focus();
  }, []);
  const [removed, setRemoved] = useState<{
    step: WorkflowStep;
    index: number;
  } | null>(null);
  const updateStep = (id: string, patch: Partial<WorkflowStep>) =>
    onChange({
      ...draft,
      steps: draft.steps.map((step) =>
        step.id === id ? { ...step, ...patch } : step,
      ),
    });
  const move = (index: number, delta: number) => {
    const steps = [...draft.steps];
    [steps[index], steps[index + delta]] = [steps[index + delta], steps[index]];
    onChange({ ...draft, steps });
  };
  return (
    <div className="grid items-start gap-8 lg:grid-cols-[240px_minmax(0,1fr)]">
      <WorkflowOutline
        steps={draft.steps}
        selected={selected}
        onSelect={onSelect}
        onAdd={
          disabled
            ? undefined
            : () => {
                const step = emptyStep();
                onChange({
                  ...draft,
                  steps: [...draft.steps, step],
                });
                onSelect(step.id);
              }
        }
      />
      <fieldset disabled={disabled} className="space-y-5 min-w-0">
        {removed && (
          <div
            role="status"
            className="rounded-xl p-4"
            style={{ background: "var(--accent-soft)" }}
          >
            Removed {removed.step.name || "Untitled step"}. Undo restores your
            most recent removal.{" "}
            <button
              key={removed.step.id}
              ref={focusUndo}
              className="af-btn af-btn-sm"
              disabled={draft.steps.length >= 50}
              onClick={() => {
                const steps = [...draft.steps];
                steps.splice(
                  Math.min(removed.index, steps.length),
                  0,
                  removed.step,
                );
                onChange({ ...draft, steps });
                setRemoved(null);
                onSelect(removed.step.id);
              }}
            >
              Undo removal
            </button>
          </div>
        )}
        {selected === "details" && (
          <section className="af-card p-6">
            <p className="mb-2 text-xs uppercase tracking-widest text-[var(--ink-3)]">
              Unsaved plan
            </p>
            <h2 className="text-xl font-semibold mb-5">Workflow details</h2>
            <Field
              label="Workflow name"
              value={draft.name}
              onChange={(name) => onChange({ ...draft, name })}
              {...field("name")}
            />
            <Field
              label="Your outcome"
              value={draft.description}
              onChange={(description) => onChange({ ...draft, description })}
              {...field("description")}
              area
            />
          </section>
        )}
        {draft.steps.length === 0 && (
          <section className="af-card p-8 text-center">
            <h2 className="text-lg font-semibold">Add your first step</h2>
            <p>A workflow needs at least one step before it can be saved.</p>
          </section>
        )}
        {draft.steps.map(
          (step, index) =>
            selected === step.id && (
              <section
                key={step.id}
                className="af-card p-5"
                aria-label={`Step ${index + 1} editor`}
              >
                <header className="mb-5 border-b border-[var(--line)] pb-5">
                  <p className="mb-2 text-xs uppercase tracking-widest text-[var(--ink-3)]">
                    Editing · Step {index + 1} of {draft.steps.length}
                  </p>
                  <h2 className="text-xl font-semibold">
                    {step.name || "Untitled step"}
                  </h2>
                </header>
                <div>
                  <div className="min-w-0">
                    <Field
                      label={`Step ${index + 1}`}
                      value={step.name}
                      onChange={(name) => updateStep(step.id, { name })}
                      {...field(stepField(step.id, "name"))}
                    />
                    <Field
                      label="What should the Agent do?"
                      value={step.goal}
                      onChange={(goal) => updateStep(step.id, { goal })}
                      {...field(stepField(step.id, "goal"))}
                      area
                    />
                    <Field
                      label="When is this step complete?"
                      value={step.completionCriteria}
                      onChange={(completionCriteria) =>
                        updateStep(step.id, {
                          completionCriteria,
                        })
                      }
                      {...field(stepField(step.id, "completionCriteria"))}
                      area
                    />
                    <label className="flex gap-2 items-center mb-4 text-sm">
                      <input
                        type="checkbox"
                        checked={step.artifactDescription !== null}
                        onChange={(e) =>
                          updateStep(step.id, {
                            artifactDescription: e.target.checked ? "" : null,
                          })
                        }
                      />
                      Preserve an output from this step
                    </label>
                    {step.artifactDescription !== null && (
                      <Field
                        label="Describe the output"
                        value={step.artifactDescription}
                        onChange={(artifactDescription) =>
                          updateStep(step.id, {
                            artifactDescription,
                          })
                        }
                        {...field(stepField(step.id, "artifactDescription"))}
                        area
                      />
                    )}
                    <div className="flex gap-2 flex-wrap">
                      <button
                        className="af-btn af-btn-sm"
                        disabled={disabled || index === 0}
                        onClick={() => move(index, -1)}
                      >
                        ↑ Move up
                      </button>
                      <button
                        className="af-btn af-btn-sm"
                        disabled={disabled || index === draft.steps.length - 1}
                        onClick={() => move(index, 1)}
                      >
                        ↓ Move down
                      </button>
                      <button
                        className="af-btn af-btn-sm"
                        onClick={() => {
                          setRemoved({ step, index });
                          const steps = draft.steps.filter(
                            (s) => s.id !== step.id,
                          );
                          onChange({
                            ...draft,
                            steps,
                          });
                          onSelect(
                            steps[Math.min(index, steps.length - 1)]?.id ??
                              "details",
                          );
                        }}
                      >
                        Remove step
                      </button>
                    </div>
                  </div>
                </div>
              </section>
            ),
        )}
        {selected === "inputs" && (
          <WorkflowInputsEditor
            inputs={draft.inputs}
            onChange={(inputs) => {
              // Input feedback is keyed by position, which removal shifts.
              if (inputs.length < draft.inputs.length)
                setTouched(
                  (current) =>
                    new Set(
                      [...current].filter((id) => !id.startsWith("input:")),
                    ),
                );
              onChange({ ...draft, inputs });
            }}
            disabled={disabled}
            errorFor={errorFor}
            onTouch={touch}
          />
        )}
        {selected === "outputs" && (
          <section className="af-card p-6">
            <h2 className="text-xl font-semibold mb-4">
              Final output & review destination
            </h2>
            <label className="flex gap-2 items-center mb-4 text-sm">
              <input
                type="checkbox"
                checked={draft.finalArtifactDescription !== null}
                onChange={(e) =>
                  onChange({
                    ...draft,
                    finalArtifactDescription: e.target.checked ? "" : null,
                  })
                }
              />
              Preserve a final output
            </label>
            {draft.finalArtifactDescription !== null && (
              <Field
                label="Describe the final output"
                value={draft.finalArtifactDescription}
                onChange={(finalArtifactDescription) =>
                  onChange({
                    ...draft,
                    finalArtifactDescription,
                  })
                }
                {...field("finalArtifactDescription")}
                area
              />
            )}
            <p className="text-sm font-medium">
              Where should review notifications go?
            </p>
            <p className="text-sm">
              Web review · Messaging notifications are unavailable.
            </p>
          </section>
        )}
      </fieldset>
    </div>
  );
}
