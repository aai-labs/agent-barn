"use client";

import { FileOutput, Info, ListFilter, Plus } from "lucide-react";
import { type ReactNode } from "react";

import { type WorkflowStep } from "../schemas";

export function WorkflowOutline({
  steps,
  selected,
  onSelect,
  onAdd,
}: {
  steps: WorkflowStep[];
  selected: string;
  onSelect: (section: string) => void;
  onAdd?: () => void;
}) {
  const sectionButton = (id: string, label: string, icon: ReactNode) => (
    <button
      type="button"
      aria-current={selected === id ? "page" : undefined}
      onClick={() => onSelect(id)}
      className="flex items-center gap-2 rounded-lg px-3 py-2.5 text-sm text-left transition-colors hover:bg-[var(--bg-soft)]"
      style={{
        color: selected === id ? "var(--ink)" : "var(--ink-3)",
        background: selected === id ? "var(--accent-soft)" : undefined,
      }}
    >
      {icon}
      {label}
    </button>
  );
  return (
    <nav
      aria-label="Workflow sections"
      className="min-w-0 lg:sticky lg:top-6 lg:self-start lg:max-h-[calc(100vh-8rem)] lg:overflow-y-auto"
    >
      {sectionButton("details", "Workflow details", <Info size={15} />)}
      <p className="mt-6 mb-3 px-3 text-[11px] font-semibold uppercase tracking-widest text-[var(--ink-3)]">
        Steps · {steps.length}
      </p>
      <ol className="flex gap-2 overflow-x-auto pb-2 lg:block lg:space-y-1 lg:overflow-visible">
        {steps.map((step, index) => (
          <li key={step.id} className="relative shrink-0 lg:shrink">
            {index < steps.length - 1 && (
              <span
                aria-hidden="true"
                className="absolute left-[26px] top-10 bottom-[-12px] hidden w-px bg-[var(--line)] lg:block"
              />
            )}
            <button
              type="button"
              aria-label={`Step ${index + 1}: ${step.name || "Untitled step"}`}
              aria-current={selected === step.id ? "step" : undefined}
              onClick={() => onSelect(step.id)}
              className="relative flex w-full items-start gap-3 rounded-xl px-3 py-3 text-left transition-colors hover:bg-[var(--bg-soft)]"
              style={{
                background:
                  selected === step.id ? "var(--accent-soft)" : undefined,
              }}
            >
              <span
                className="grid size-7 shrink-0 place-items-center rounded-full border text-xs font-semibold"
                style={{
                  background: selected === step.id ? "var(--ink)" : "var(--bg)",
                  color: selected === step.id ? "var(--bg)" : "var(--ink-3)",
                  borderColor:
                    selected === step.id ? "var(--ink)" : "var(--line)",
                }}
              >
                {index + 1}
              </span>
              <span className="min-w-0 pt-0.5">
                <span className="block max-w-48 break-words text-sm font-medium">
                  {step.name || "Untitled step"}
                </span>
                <span className="mt-1 hidden text-xs text-[var(--ink-3)] lg:block">
                  {step.artifactDescription !== null
                    ? "Output planned"
                    : "Workflow step"}
                </span>
              </span>
            </button>
          </li>
        ))}
      </ol>
      {onAdd && (
        <button
          type="button"
          className="af-btn af-btn-ghost af-btn-sm mt-2"
          disabled={steps.length >= 50}
          onClick={onAdd}
        >
          <Plus size={14} /> Add a step
        </button>
      )}
      <div className="mt-5 flex flex-wrap gap-1 border-t border-[var(--line)] pt-3 lg:flex-col">
        {sectionButton("inputs", "Required inputs", <ListFilter size={15} />)}
        {sectionButton("outputs", "Outputs & review", <FileOutput size={15} />)}
      </div>
    </nav>
  );
}
