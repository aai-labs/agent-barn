import type { Agent, AgentHealth } from "../schemas";

export interface AgentStatusView {
  label: "Needs attention" | "Idle" | "Initializing" | "Working" | "Disconnected";
  /** The dot's colour. */
  color: string;
  /** The label's colour, which is quieter than the dot for an idle Agent. */
  textColor: string;
  /** Whether the dot pulses: the Agent is starting up or at work. */
  pulse: boolean;
}

/**
 * How an Agent is doing, in one word, from its lifecycle status and its runtime's health.
 * Every place that shows an Agent's status reads it from here, so they cannot disagree.
 */
export function agentStatus(status: Agent["status"], health?: AgentHealth | null): AgentStatusView {
  if (status === "ERROR" || health?.status === "crashed") {
    return { label: "Needs attention", color: "var(--err)", textColor: "var(--err)", pulse: false };
  }
  if (status === "STOPPED") {
    return { label: "Idle", color: "var(--ink-4)", textColor: "var(--ink-3)", pulse: false };
  }
  if (!health || health.status === "starting" || health.status === "initializing") {
    return { label: "Initializing", color: "var(--ok)", textColor: "var(--ok)", pulse: true };
  }
  if (health.status === "ok") {
    return { label: "Working", color: "var(--ok)", textColor: "var(--ok)", pulse: true };
  }
  return { label: "Disconnected", color: "var(--warn, #f59e0b)", textColor: "var(--warn, #f59e0b)", pulse: false };
}

interface StatusLineProps {
  status: Agent["status"];
  health?: AgentHealth | null;
}

export function StatusLine({ status, health }: StatusLineProps) {
  const view = agentStatus(status, health);
  return (
    <span className="inline-flex items-center gap-1.5 text-[12.5px]" style={{ color: view.textColor }}>
      <span
        className={`w-1.5 h-1.5 rounded-full inline-block flex-shrink-0${view.pulse ? " af-dot-pulse" : ""}`}
        style={{ background: view.color }}
      />
      {view.label}
    </span>
  );
}
