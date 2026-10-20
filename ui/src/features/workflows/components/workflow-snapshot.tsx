"use client";

import { useState } from "react";

import { type WorkflowVersion } from "../schemas";
import { WorkflowOutline } from "./workflow-outline";

export function WorkflowSnapshot({ version }: { version: WorkflowVersion }) {
  const [selected, setSelected] = useState(
    version.draft.steps[0]?.id ?? "details",
  );
  const { draft } = version;
  const index = draft.steps.findIndex((step) => step.id === selected);
  const step = draft.steps[index];
  return (
    <div className="grid items-start gap-8 lg:grid-cols-[240px_minmax(0,1fr)]">
      <WorkflowOutline
        steps={draft.steps}
        selected={selected}
        onSelect={setSelected}
      />
      <section
        className="af-card min-w-0 overflow-hidden"
        aria-label="Saved workflow section"
      >
        <header className="border-b border-[var(--line)] bg-[var(--bg-soft)] px-6 py-5">
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-widest text-[var(--ink-3)]">
            Saved v{version.number}
            {step
              ? ` · Step ${index + 1} of ${draft.steps.length}`
              : " · Workflow plan"}
          </p>
          <h2 className="text-xl font-semibold">
            {step?.name ??
              (selected === "details"
                ? "Workflow details"
                : selected === "inputs"
                  ? "Required inputs"
                  : "Outputs & review")}
          </h2>
        </header>
        <div className="space-y-6 p-6">
          {step ? (
            <>
              <div>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--ink-3)]">
                  What the Agent should do
                </h3>
                <p className="whitespace-pre-wrap text-sm leading-6">
                  {step.goal}
                </p>
              </div>
              <div className="rounded-xl bg-[var(--bg-soft)] p-4">
                <h3 className="mb-2 text-sm font-semibold">Complete when</h3>
                <p className="whitespace-pre-wrap text-sm leading-6">
                  {step.completionCriteria}
                </p>
              </div>
              <div>
                <h3 className="mb-2 text-sm font-semibold">Preserved output</h3>
                <p className="whitespace-pre-wrap text-sm leading-6">
                  {step.artifactDescription ??
                    "No output is planned for this step."}
                </p>
              </div>
            </>
          ) : selected === "details" ? (
            <>
              <p className="whitespace-pre-wrap text-sm leading-6">
                {draft.description}
              </p>
              <p className="text-sm text-[var(--ink-3)]">
                {draft.steps.length} steps · {draft.inputs.length} inputs · Web
                review
              </p>
            </>
          ) : selected === "inputs" ? (
            draft.inputs.length ? (
              draft.inputs.map((input) => (
                <div
                  key={input.key}
                  className="border-b border-[var(--line)] pb-4 last:border-0"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h3 className="font-semibold">{input.label}</h3>
                    <span className="text-xs text-[var(--ink-3)]">
                      {input.type} · {input.required ? "Required" : "Optional"}
                    </span>
                  </div>
                  <p className="mt-2 whitespace-pre-wrap text-sm">
                    {input.description}
                  </p>
                </div>
              ))
            ) : (
              <p className="text-sm">This workflow has no required inputs.</p>
            )
          ) : (
            <>
              <div>
                <h3 className="mb-2 font-semibold">Final output</h3>
                <p className="whitespace-pre-wrap text-sm">
                  {draft.finalArtifactDescription ??
                    "No final output is planned."}
                </p>
              </div>
              <div>
                <h3 className="mb-2 font-semibold">Review destination</h3>
                <p className="text-sm">Web review</p>
              </div>
            </>
          )}
        </div>
        <footer className="border-t border-[var(--line)] px-6 py-4 text-xs text-[var(--ink-3)]">
          This is a saved plan. Saved versions retain their steps and outputs;
          execution is unavailable.
        </footer>
      </section>
    </div>
  );
}
