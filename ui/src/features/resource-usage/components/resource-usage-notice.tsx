import { Info, RefreshCw } from "lucide-react";

import type { ResourceUsageAvailability, ResourceUsageState } from "../schemas";

interface Message {
  title: string;
  body: string;
}

/**
 * What to tell a reader when there is no usage to show, and why.
 *
 * One message per cause, because they call for different actions: a source that is
 * down is retried, an Agent on an older script is restarted, and an unconfigured
 * environment has nothing to do.
 */
export function noticeFor(
  availability: ResourceUsageAvailability,
  state: ResourceUsageState | null,
): Message | null {
  if (availability === "not_configured") {
    return {
      title: "Resource usage isn't set up here",
      body: "This environment has no monitoring service configured, so CPU and memory can't be shown. Status and cost are unaffected.",
    };
  }
  if (availability === "unavailable") {
    return {
      title: "Resource usage is unavailable right now",
      body: "We couldn't reach the monitoring service. Status and cost are unaffected. Try again in a moment.",
    };
  }
  switch (state) {
    case "restart_required":
      return {
        title: "Restart this agent to start reporting CPU and memory",
        body: "It is running an older version of the helper that reports usage. Figures appear about a minute after it restarts.",
      };
    case "unsupported":
      return {
        title: "This agent's host can't report resource usage",
        body: "Its container can't read cgroup v2 statistics. That depends on the cluster node, not on the agent.",
      };
    case "no_data":
      return {
        title: "No usage recorded for this period",
        body: "Usage is recorded while an agent is running. Start it and figures appear within a couple of minutes.",
      };
    default:
      return null;
  }
}

export function ResourceUsageNotice({
  availability,
  state,
  onRetry,
  isRetrying,
}: {
  availability: ResourceUsageAvailability;
  state: ResourceUsageState | null;
  onRetry?: () => void;
  isRetrying?: boolean;
}) {
  const message = noticeFor(availability, state);
  if (!message) return null;
  const canRetry = availability === "unavailable" && !!onRetry;

  return (
    <div
      className="af-card flex flex-col gap-3 p-4 sm:flex-row sm:items-start sm:justify-between"
      role="status"
      data-testid="resource-usage-notice"
      data-availability={availability}
      data-state={state ?? undefined}
    >
      <div className="flex min-w-0 items-start gap-3">
        <Info size={18} className="mt-0.5 flex-shrink-0" style={{ color: "var(--ink-4)" }} />
        <div className="min-w-0">
          <p className="m-0 text-[14px] font-semibold" style={{ color: "var(--ink)" }}>
            {message.title}
          </p>
          <p className="m-0 mt-1 text-[13px] leading-relaxed" style={{ color: "var(--ink-3)" }}>
            {message.body}
          </p>
        </div>
      </div>
      {canRetry && (
        <button
          type="button"
          className="af-btn af-btn-sm flex-shrink-0 self-start"
          onClick={onRetry}
          disabled={isRetrying}
        >
          <RefreshCw size={14} /> Retry
        </button>
      )}
    </div>
  );
}
