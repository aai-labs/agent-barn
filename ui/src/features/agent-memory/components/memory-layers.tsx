"use client";

import { ChevronRight } from "lucide-react";

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import type { Agent } from "@/features/agents/schemas";

import { BUILT_IN_MEMORY_LABEL, builtInMemoryDescription } from "../utils";

/** A state chip shared by both memory layers: green when active, neutral when not. */
export function MemoryStateBadge({ label, active }: { label: string; active: boolean }) {
  return (
    <span
      className="inline-flex items-center rounded-full px-2 py-0.5 text-[0.72rem] font-medium"
      style={{
        background: active ? "var(--ok-soft)" : "var(--bg-soft)",
        border: `1px solid ${active ? "color-mix(in srgb, var(--ok) 35%, var(--line))" : "var(--line)"}`,
        color: active ? "var(--ok)" : "var(--ink-3)",
      }}
    >
      {label}
    </span>
  );
}

/**
 * Tells people the runtime's own notes exist. Agents always have them, they cannot be
 * turned off, and nothing else in the product shows them, so without this the opt-in
 * long-term memory reads as the Agent having no memory at all.
 *
 * `card` states it in full; `line` is a quiet one-liner with the description behind
 * "Details", for screens where the long-term memory list is the focus.
 */
export function BuiltInMemoryNotice({
  agent,
  variant,
  footnote,
}: {
  agent: Pick<Agent, "agentType">;
  variant: "card" | "line";
  /** Extra sentence for the card, e.g. that this layer cannot be switched off. */
  footnote?: string;
}) {
  const description = builtInMemoryDescription(agent.agentType);

  if (variant === "card") {
    return (
      <section
        aria-label={BUILT_IN_MEMORY_LABEL}
        className="rounded-xl p-4"
        style={{ border: "1px solid var(--line)", background: "var(--bg-soft)" }}
      >
        <div className="mb-1 flex flex-wrap items-center gap-2">
          <span className="text-[0.9rem] font-semibold" style={{ color: "var(--ink)" }}>
            {BUILT_IN_MEMORY_LABEL}
          </span>
          <MemoryStateBadge label="Always on" active />
        </div>
        <p className="m-0 text-[0.84rem] leading-relaxed" style={{ color: "var(--ink-3)" }}>
          {description}
          {footnote ? ` ${footnote}` : null}
        </p>
      </section>
    );
  }

  return (
    <Collapsible asChild>
      <section
        aria-label={BUILT_IN_MEMORY_LABEL}
        className="rounded-xl px-3.5 py-2.5"
        style={{ border: "1px dashed var(--line-strong)" }}
      >
        <div className="flex flex-wrap items-center justify-between gap-2 text-[0.84rem]">
          <span className="flex flex-wrap items-center gap-2" style={{ color: "var(--ink-3)" }}>
            <span className="font-semibold" style={{ color: "var(--ink)" }}>
              {BUILT_IN_MEMORY_LABEL}
            </span>
            <MemoryStateBadge label="Always on" active />
          </span>
          <CollapsibleTrigger asChild>
            <button
              type="button"
              className="group inline-flex items-center gap-1 text-[0.8rem] underline"
              style={{ color: "var(--ink-3)" }}
            >
              Details
              <ChevronRight size={14} className="transition-transform group-data-[state=open]:rotate-90" />
            </button>
          </CollapsibleTrigger>
        </div>
        <CollapsibleContent>
          <p className="mb-0 mt-2 text-[0.84rem] leading-relaxed" style={{ color: "var(--ink-3)" }}>
            {description}
          </p>
        </CollapsibleContent>
      </section>
    </Collapsible>
  );
}

const COMPARISON_ROWS: ReadonlyArray<readonly [string, string, string]> = [
  ["Stored", "On the Agent's disk", "Outside the Agent, in Agent Barn"],
  ["Who sees it", "This Agent only", "Everyone who uses it; can be shared with other Agents"],
  ["Viewable here", "Not yet", "Memory tab"],
  ["Restore points", "Part of the Agent's files", "Not rolled back"],
  ["Turning it off", "Not possible", "Immediate; saved memories are kept"],
];

/**
 * How the two memory layers differ. Collapsed by default: it is reference material, and
 * the operational notes beside it stay visible.
 */
export function MemoryLayerComparison() {
  return (
    <Collapsible>
      <CollapsibleTrigger asChild>
        <button
          type="button"
          className="group inline-flex items-center gap-1.5 text-[0.84rem] font-medium"
          style={{ color: "var(--ink)" }}
        >
          <ChevronRight size={14} className="transition-transform group-data-[state=open]:rotate-90" />
          How is this different from built-in memory?
        </button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full border-collapse text-left text-[0.8rem]">
            <thead>
              <tr style={{ color: "var(--ink-4)" }}>
                <th scope="col" className="px-2.5 py-2 text-[0.7rem] font-semibold uppercase tracking-wide">
                  <span className="sr-only">Aspect</span>
                </th>
                <th scope="col" className="px-2.5 py-2 text-[0.7rem] font-semibold uppercase tracking-wide">
                  Built-in memory
                </th>
                <th scope="col" className="px-2.5 py-2 text-[0.7rem] font-semibold uppercase tracking-wide">
                  Long-term memory
                </th>
              </tr>
            </thead>
            <tbody>
              {COMPARISON_ROWS.map(([aspect, builtIn, longTerm]) => (
                <tr key={aspect} style={{ borderTop: "1px solid var(--line)" }}>
                  <th scope="row" className="w-1/4 px-2.5 py-2 align-top font-normal" style={{ color: "var(--ink-4)" }}>
                    {aspect}
                  </th>
                  <td className="px-2.5 py-2 align-top" style={{ color: "var(--ink-2)" }}>
                    {builtIn}
                  </td>
                  <td className="px-2.5 py-2 align-top" style={{ color: "var(--ink-2)" }}>
                    {longTerm}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
