"use client";

import { useId, useState } from "react";
import { ChevronDown, Loader2 } from "lucide-react";

import { SettingsSectionHeading } from "@/components/settings/settings-section-heading";
import { ModelSourceBadge } from "@/features/agents/components/model-source-badge";
import { PendingModelNote } from "@/features/agents/components/pending-model-note";
import { useAgents } from "@/features/agents/hooks/use-agents";
import { currentModelOf, formatModelName } from "@/features/agents/utils";

import { useAgentSettings } from "../hooks/use-agent-settings";

/**
 * Who actually follows the default, named.
 *
 * The section above reports how many Agents inherit versus override; that number tells
 * you the size of a change but not which Agents it lands on. This answers that, and it
 * is the only place the two model facts sit side by side per Agent — what each one is
 * running now, and whether a default change would move it.
 *
 * Collapsed by default: it is reference material for a change being considered, not
 * something to scroll past on the way to the controls.
 */
export function AgentModelMapSection() {
  const [open, setOpen] = useState(false);
  const { agents, total, isLoading } = useAgents();
  const { settings } = useAgentSettings();
  const panelId = useId();

  const inheriting = settings?.inheritingAgentCount;

  return (
    <section className="af-card overflow-hidden" aria-label="Agent models">
      <button
        type="button"
        className="af-hover-bg flex w-full cursor-pointer items-center justify-between gap-4 p-5 text-left"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((current) => !current)}
      >
        <SettingsSectionHeading
          title="Agent models"
          description="Which model each Agent is on, and whether it follows the default."
        />
        <span className="flex flex-shrink-0 items-center gap-3">
          {!isLoading && total > 0 && (
            <span className="text-[0.8rem]" style={{ color: "var(--ink-3)" }}>
              {inheriting ?? "—"} of {total} follow the default
            </span>
          )}
          {/* Styled as a button rather than a bare chevron: the card is read-only, so
              nothing else on it signals that it does anything when clicked. */}
          <span className="af-btn af-btn-sm">
            {open ? "Hide" : "Show"} Agents
            <ChevronDown
              size={14}
              style={{
                transition: "transform .15s",
                transform: open ? "rotate(180deg)" : undefined,
              }}
              aria-hidden
            />
          </span>
        </span>
      </button>

      {open && (
        <div id={panelId} className="px-5 py-2" style={{ borderTop: "1px solid var(--line)" }}>
          {isLoading ? (
            <div
              className="flex items-center gap-2 py-3 text-[0.84rem]"
              style={{ color: "var(--ink-3)" }}
            >
              <Loader2 size={15} className="animate-spin" /> Loading Agents…
            </div>
          ) : agents.length === 0 ? (
            <p className="my-3 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
              This organization has no Agents yet.
            </p>
          ) : (
            <ul className="m-0 flex list-none flex-col p-0">
              {agents.map((agent, index) => (
                <li
                  key={agent.id}
                  className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-2.5"
                  style={index > 0 ? { borderTop: "1px solid var(--line)" } : undefined}
                >
                  <div className="min-w-0">
                    <div
                      className="truncate text-[0.84rem] font-medium"
                      style={{ color: "var(--ink)" }}
                    >
                      {agent.name}
                    </div>
                    <PendingModelNote pendingModel={agent.pendingModel} />
                  </div>
                  <div className="flex flex-shrink-0 items-center gap-2">
                    <span className="font-mono text-[0.8rem]" style={{ color: "var(--ink-2)" }}>
                      {formatModelName(currentModelOf(agent)) || "—"}
                    </span>
                    <ModelSourceBadge source={agent.modelSource} />
                  </div>
                </li>
              ))}
            </ul>
          )}
          {agents.length < total && (
            <p className="my-3 text-[0.8rem]" style={{ color: "var(--ink-3)" }}>
              Showing the first {agents.length} of {total} Agents.
            </p>
          )}
        </div>
      )}
    </section>
  );
}
