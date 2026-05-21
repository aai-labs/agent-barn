import type { Agent, AgentHealth } from "../schemas";

interface StatusLineProps {
  status: Agent["status"];
  health?: AgentHealth | null;
}

export function StatusLine({ status, health }: StatusLineProps) {
  if (status === "ERROR") {
    return (
      <span className="inline-flex items-center gap-1.5 text-[12.5px]" style={{ color: "var(--err)" }}>
        <span className="w-1.5 h-1.5 rounded-full inline-block flex-shrink-0" style={{ background: "var(--err)" }} />
        Needs attention
      </span>
    );
  }

  if (status === "STOPPED") {
    return (
      <span className="inline-flex items-center gap-1.5 text-[12.5px]" style={{ color: "var(--ink-3)" }}>
        <span className="w-1.5 h-1.5 rounded-full inline-block flex-shrink-0" style={{ background: "var(--ink-4)" }} />
        Idle
      </span>
    );
  }

  if (!health || health.status === "starting") {
    return (
      <span className="inline-flex items-center gap-1.5 text-[12.5px]" style={{ color: "var(--ok)" }}>
        <span className="w-1.5 h-1.5 rounded-full inline-block flex-shrink-0 af-dot-pulse" style={{ background: "var(--ok)" }} />
        Working
      </span>
    );
  }

  if (health.status === "ok") {
    return (
      <span className="inline-flex items-center gap-1.5 text-[12.5px]" style={{ color: "var(--ok)" }}>
        <span className="w-1.5 h-1.5 rounded-full inline-block flex-shrink-0 af-dot-pulse" style={{ background: "var(--ok)" }} />
        Connected
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-1.5 text-[12.5px]" style={{ color: "var(--warn, #f59e0b)" }}>
      <span className="w-1.5 h-1.5 rounded-full inline-block flex-shrink-0" style={{ background: "var(--warn, #f59e0b)" }} />
      Disconnected
    </span>
  );
}
