"use client";

import { Check, ChevronDown, ChevronUp, Plus, Trash2, UserCheck } from "lucide-react";
import { useId, useMemo, useState } from "react";

import { ConfirmationDialog } from "@/components/confirmation-dialog";


import {
  STEP_DECISIONS,
  type StepDecision,
  type WorkflowDraft,
  type WorkflowStep,
} from "../schemas";
import {
  stepField,
  workflowFieldErrors,
  type WorkflowProblem,
} from "../validation";
import { stepNameFromGoal } from "../utils";
import { AgentPillPicker, type AgentChoice } from "./agent-pill-picker";
import { WorkflowInputsEditor } from "./workflow-inputs-editor";

export function emptyStep(type: WorkflowStep["type"] = "agent"): WorkflowStep {
  return {
    id: crypto.randomUUID(),
    type,
    ...(type === "approval" ? { allowedDecisions: [...STEP_DECISIONS] } : {}),
    name: "",
    goal: "",
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
    reviewDestination: "web",
  };
}

/** Step reorder chevrons: a soft fill on hover, a firmer one while pressed. */
const reorderButton =
  "grid size-6 place-items-center rounded-md text-[var(--ink-3)] transition-colors hover:bg-[var(--bg-soft)] hover:text-[var(--ink)] active:bg-[var(--line-strong)] active:text-[var(--ink)] focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--accent-color)] disabled:pointer-events-none disabled:opacity-30";

const count = (value: number, noun: string) =>
  `${value} ${value === 1 ? noun : `${noun}s`}`;

/** A labelled text control of the editor; its validation message shows once revealed. */
function Control({
  label,
  hideLabel = false,
  value,
  onChange,
  onBlur,
  error,
  placeholder,
  area = false,
  large = false,
  className = "",
}: {
  label: string;
  /** Names the control for assistive technology without a visible label. */
  hideLabel?: boolean;
  value: string;
  onChange: (value: string) => void;
  onBlur?: () => void;
  error?: string;
  placeholder?: string;
  area?: boolean;
  large?: boolean;
  className?: string;
}) {
  const id = useId();
  const errorId = `${id}-error`;
  const control = {
    id,
    className: `af-input block w-full${area ? " min-h-20" : ""}${large ? " text-base" : ""}`,
    value,
    placeholder,
    onChange: (
      event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>,
    ) => onChange(event.target.value),
    onBlur,
    "aria-label": hideLabel ? label : undefined,
    "aria-invalid": error ? true : undefined,
    "aria-describedby": error ? errorId : undefined,
    style: error ? { borderColor: "var(--err)" } : undefined,
  };
  return (
    <div className={`min-w-0 ${className}`}>
      {!hideLabel && (
        <label htmlFor={id} className="mb-1.5 block text-sm font-semibold">
          {label}
        </label>
      )}
      {area ? <textarea {...control} /> : <input {...control} />}
      {error && (
        <p id={errorId} className="mt-1.5 text-xs" style={{ color: "var(--err)" }}>
          {error}
        </p>
      )}
    </div>
  );
}

const decisionLabel: Record<StepDecision, string> = {
  approve: "Approve",
  request_changes: "Request changes",
  reject: "Reject",
};

/** Which decisions the person at an Approval step is offered; Approve always is. */
function AllowedDecisions({
  stepNumber,
  value,
  onChange,
}: {
  stepNumber: number;
  value: StepDecision[];
  onChange: (value: StepDecision[]) => void;
}) {
  return (
    <div className="mt-2 flex flex-wrap items-center gap-2">
      <span aria-hidden="true" className="text-xs text-[var(--ink-3)]">
        Allowed decisions
      </span>
      <div
        role="group"
        aria-label={`Step ${stepNumber} allowed decisions`}
        className="flex flex-wrap gap-1.5"
      >
        {STEP_DECISIONS.map((decision) => {
          const on = value.includes(decision);
          const locked = decision === "approve";
          return (
            <button
              key={decision}
              type="button"
              aria-pressed={on}
              // Approve is always offered: without it the step could only stop the run.
              disabled={locked}
              title={locked ? "Approve is always allowed" : undefined}
              onClick={() =>
                onChange(
                  STEP_DECISIONS.filter((item) =>
                    item === decision ? !on : value.includes(item),
                  ),
                )
              }
              className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--accent-color)] disabled:cursor-default ${on ? "bg-[var(--ink)] text-[var(--bg)]" : "border border-[var(--line-strong)] bg-[var(--bg-elev)] text-[var(--ink-3)] hover:text-[var(--ink)]"}`}
            >
              {on && <Check size={12} aria-hidden="true" />}
              {decisionLabel[decision]}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export type DefaultAgentChoice = AgentChoice;

/**
 * The workflow form: its name and purpose, the Agent runs start with by default, its
 * steps in order, and the inputs a run asks for. Every step is open at once.
 */
export function WorkflowEditor({
  draft,
  onChange,
  disabled,
  problems,
  revealed,
  agents,
  defaultAgentId,
  onDefaultAgentChange,
}: {
  draft: WorkflowDraft;
  onChange: (draft: WorkflowDraft) => void;
  disabled: boolean;
  /** Problems from the last save attempt, including server validation. */
  problems: WorkflowProblem[];
  /** After a save attempt every invalid field shows its message. */
  revealed: boolean;
  /** Agents the author can see, offered as the default for runs. */
  agents: DefaultAgentChoice[];
  defaultAgentId: string | null;
  onDefaultAgentChange: (agentId: string | null) => void;
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
  // A step with a prompt is removed only after confirmation; an empty one goes at once.
  const [removing, setRemoving] = useState<{ step: WorkflowStep; index: number } | null>(
    null,
  );
  const removeStep = (id: string) =>
    onChange({ ...draft, steps: draft.steps.filter((item) => item.id !== id) });
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
    <fieldset disabled={disabled} className="min-w-0 space-y-6">
      <div data-section="details" className="space-y-4">
        <Control
          label="Name"
          large
          placeholder="e.g. Weekly release notes"
          value={draft.name}
          onChange={(name) => onChange({ ...draft, name })}
          {...field("name")}
        />
        <Control
          label="What does it do?"
          area
          placeholder="One or two sentences a teammate could read to know when to run this."
          value={draft.description}
          onChange={(description) => onChange({ ...draft, description })}
          {...field("description")}
        />
        <div>
          <p id="workflow-default-agent" className="mb-1.5 text-sm font-semibold">
            Default agent{" "}
            <span className="font-normal text-[var(--ink-3)]">(optional)</span>
          </p>
          <AgentPillPicker
            labelledBy="workflow-default-agent"
            agents={agents}
            value={defaultAgentId}
            onChange={onDefaultAgentChange}
            noneLabel="No default"
          />
          <p className="mt-1.5 text-xs text-[var(--ink-3)]">
            Preselected under “Run as”. Whoever starts a run can pick another agent.
          </p>
        </div>
      </div>

      <div>
        <div className="mb-2 flex items-baseline justify-between">
          <h3 className="text-sm font-semibold">Steps</h3>
          <span className="text-xs text-[var(--ink-3)]">
            {count(draft.steps.length, "step")}
          </span>
        </div>
        {draft.steps.length === 0 && (
          <p className="rounded-xl border border-dashed border-[var(--line-strong)] p-5 text-center text-sm text-[var(--ink-3)]">
            A workflow needs at least one step before it can be saved.
          </p>
        )}
        <ol className="space-y-2.5">
          {draft.steps.map((step, index) => {
            const approval = step.type === "approval";
            return (
              <li
                key={step.id}
                data-section={step.id}
                aria-label={approval ? `Step ${index + 1} · Approval step` : `Step ${index + 1}`}
                className={`group/step flex gap-3 rounded-2xl border p-3 transition-colors focus-within:border-[var(--line-strong)] ${approval ? "border-dashed border-[var(--warn)] bg-[var(--warn-soft)]" : "border-[var(--line)] bg-[var(--bg-elev)]"}`}
              >
                <div className="flex shrink-0 flex-col items-center gap-0.5">
                  {/* The step being edited shows its number in the accent colour. */}
                  <span className="grid size-6 place-items-center rounded-full bg-[var(--bg-soft)] text-xs font-semibold transition-colors group-focus-within/step:bg-[var(--accent-color)] group-focus-within/step:text-white">
                    {index + 1}
                  </span>
                  <button
                    type="button"
                    className={reorderButton}
                    aria-label={`Move step ${index + 1} up`}
                    disabled={disabled || index === 0}
                    onClick={() => move(index, -1)}
                  >
                    <ChevronUp size={14} />
                  </button>
                  <button
                    type="button"
                    className={reorderButton}
                    aria-label={`Move step ${index + 1} down`}
                    disabled={disabled || index === draft.steps.length - 1}
                    onClick={() => move(index, 1)}
                  >
                    <ChevronDown size={14} />
                  </button>
                </div>
                <div className="flex min-w-0 flex-1 items-start gap-2">
                  <div className="min-w-0 flex-1">
                    {approval && (
                      <p
                        className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold"
                        style={{ color: "var(--warn)" }}
                      >
                        <UserCheck size={14} aria-hidden="true" /> Approval step · a person
                        decides on the step before
                      </p>
                    )}
                    <Control
                      label={
                        approval
                          ? `Step ${index + 1} approval instructions`
                          : `Step ${index + 1} instructions`
                      }
                      hideLabel
                      area
                      placeholder={
                        approval
                          ? "What should the person deciding check? e.g. Are the numbers right and the tone on brand?"
                          : "What should the agent do in this step, and what should it produce?"
                      }
                      value={step.goal}
                      // The step's name, shown in run lists and the timeline, follows its prompt.
                      onChange={(goal) =>
                        updateStep(step.id, { goal, name: stepNameFromGoal(goal) })
                      }
                      {...field(stepField(step.id, "goal"))}
                    />
                    {approval && (
                      <AllowedDecisions
                        stepNumber={index + 1}
                        value={step.allowedDecisions ?? [...STEP_DECISIONS]}
                        onChange={(allowedDecisions) =>
                          updateStep(step.id, { allowedDecisions })
                        }
                      />
                    )}
                  </div>
                  <button
                    type="button"
                    className="af-btn af-btn-icon af-btn-sm mt-0.5 shrink-0"
                    aria-label={`Remove step ${index + 1}`}
                    onClick={() =>
                      step.goal.trim()
                        ? setRemoving({ step, index })
                        : removeStep(step.id)
                    }
                  >
                    <Trash2 size={15} />
                  </button>
                </div>
              </li>
            );
          })}
        </ol>
        <p className="mt-2 text-xs text-[var(--ink-3)]">
          Each step runs with the skills and tools of the agent chosen for the run. An
          approval step pauses the run until someone who can edit that agent approves the
          step before it, asks for changes (that step runs again with their notes) or
          rejects the run.
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="text-sm text-[var(--ink-3)]">Add step:</span>
          <button
            type="button"
            className="af-btn af-btn-sm"
            aria-label="Add agent step"
            disabled={disabled || draft.steps.length >= 50}
            onClick={() =>
              onChange({ ...draft, steps: [...draft.steps, emptyStep()] })
            }
          >
            <Plus size={14} /> Agent
          </button>
          <button
            type="button"
            className="af-btn af-btn-sm"
            aria-label="Add approval step"
            // An approval step reviews the agent step before it.
            disabled={
              disabled ||
              draft.steps.length >= 50 ||
              draft.steps.at(-1)?.type !== "agent"
            }
            onClick={() =>
              onChange({ ...draft, steps: [...draft.steps, emptyStep("approval")] })
            }
          >
            <UserCheck size={14} /> Approval
          </button>
        </div>
      </div>

      <ConfirmationDialog
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
        title={`Remove step ${(removing?.index ?? 0) + 1}?`}
        description="Its prompt is deleted from this draft. Saved versions and past runs keep it."
        confirmLabel="Remove step"
        variant="destructive"
        icon={<Trash2 size={18} />}
        onConfirm={() => {
          if (removing) removeStep(removing.step.id);
          setRemoving(null);
        }}
      />

      <div data-section="inputs">
        <WorkflowInputsEditor
          inputs={draft.inputs}
          onChange={(inputs) => {
            // Input feedback is keyed by position, which removal shifts.
            if (inputs.length < draft.inputs.length)
              setTouched(
                (current) =>
                  new Set([...current].filter((id) => !id.startsWith("input:"))),
              );
            onChange({ ...draft, inputs });
          }}
          disabled={disabled}
          errorFor={errorFor}
          onTouch={touch}
        />
      </div>
    </fieldset>
  );
}
