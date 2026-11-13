"use client";

import { ChevronDown, ChevronUp, Plus, Trash2 } from "lucide-react";
import { useCallback, useId, useMemo, useState } from "react";

import { AgentAvatar } from "@/features/agents/components/agent-avatar";

import { type WorkflowDraft, type WorkflowStep } from "../schemas";
import {
  stepField,
  workflowFieldErrors,
  type WorkflowProblem,
} from "../validation";
import { stepNameFromGoal } from "../utils";
import { WorkflowInputsEditor } from "./workflow-inputs-editor";

export function emptyStep(): WorkflowStep {
  return {
    id: crypto.randomUUID(),
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

export type DefaultAgentChoice = { id: string; name: string };

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
  const chip = (selected: boolean) =>
    `inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm transition-colors ${
      selected
        ? "border-[var(--ink)] bg-[var(--ink)] text-[var(--bg)]"
        : "border-[var(--line-strong)] bg-[var(--bg-elev)] hover:bg-[var(--bg-soft)]"
    }`;
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
          <div
            role="radiogroup"
            aria-labelledby="workflow-default-agent"
            className="flex flex-wrap gap-2"
          >
            <button
              type="button"
              role="radio"
              aria-checked={defaultAgentId === null}
              className={chip(defaultAgentId === null)}
              onClick={() => onDefaultAgentChange(null)}
            >
              No default
            </button>
            {agents.map((agent) => (
              <button
                key={agent.id}
                type="button"
                role="radio"
                aria-checked={defaultAgentId === agent.id}
                className={`${chip(defaultAgentId === agent.id)} pl-1.5`}
                onClick={() => onDefaultAgentChange(agent.id)}
              >
                <span aria-hidden="true">
                      <AgentAvatar agent={agent} size="xs" />
                    </span>
                {agent.name}
              </button>
            ))}
          </div>
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
        {removed && (
          <div
            role="status"
            className="mb-2 rounded-xl p-3 text-sm"
            style={{ background: "var(--accent-soft)" }}
          >
            Removed {removed.step.name || "Untitled step"}.{" "}
            <button
              key={removed.step.id}
              ref={focusUndo}
              type="button"
              className="af-btn af-btn-sm"
              disabled={draft.steps.length >= 50}
              onClick={() => {
                const steps = [...draft.steps];
                steps.splice(Math.min(removed.index, steps.length), 0, removed.step);
                onChange({ ...draft, steps });
                setRemoved(null);
              }}
            >
              Undo removal
            </button>
          </div>
        )}
        {draft.steps.length === 0 && (
          <p className="rounded-xl border border-dashed border-[var(--line-strong)] p-5 text-center text-sm text-[var(--ink-3)]">
            A workflow needs at least one step before it can be saved.
          </p>
        )}
        <ol className="space-y-2.5">
          {draft.steps.map((step, index) => (
            <li
              key={step.id}
              data-section={step.id}
              aria-label={`Step ${index + 1}`}
              className="group/step flex gap-3 rounded-2xl border border-[var(--line)] bg-[var(--bg-elev)] p-3 transition-colors focus-within:border-[var(--line-strong)]"
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
                <Control
                  className="flex-1"
                  label={`Step ${index + 1} instructions`}
                  hideLabel
                  area
                  placeholder="What should the agent do in this step, and what should it produce?"
                  value={step.goal}
                  // The step's name, shown in run lists and the timeline, follows its prompt.
                  onChange={(goal) =>
                    updateStep(step.id, { goal, name: stepNameFromGoal(goal) })
                  }
                  {...field(stepField(step.id, "goal"))}
                />
                <button
                  type="button"
                  className="af-btn af-btn-icon af-btn-sm mt-0.5 shrink-0"
                  aria-label={`Remove step ${index + 1}`}
                  onClick={() => {
                    setRemoved({ step, index });
                    onChange({
                      ...draft,
                      steps: draft.steps.filter((item) => item.id !== step.id),
                    });
                  }}
                >
                  <Trash2 size={15} />
                </button>
              </div>
            </li>
          ))}
        </ol>
        <p className="mt-2 text-xs text-[var(--ink-3)]">
          Each step runs with the skills and tools of the agent chosen for the run.
        </p>
        <button
          type="button"
          className="af-btn af-btn-sm mt-3"
          disabled={disabled || draft.steps.length >= 50}
          onClick={() =>
            onChange({ ...draft, steps: [...draft.steps, emptyStep()] })
          }
        >
          <Plus size={14} /> Add step
        </button>
      </div>

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
