import { describeProvisioningFailure } from "../provisioning-failure";
import type { AgentProvisioningError } from "../schemas";

/**
 * Shows why an Agent is in ERROR. Read from the Agent itself, so it appears on
 * first render and survives a refresh until a successful start clears it.
 */
export function AgentErrorBanner({
  failure,
}: {
  failure: AgentProvisioningError;
}) {
  const { title, summary, detail } = describeProvisioningFailure(failure);

  return (
    <div
      role="alert"
      data-testid="agent-error-banner"
      className="mb-6 rounded-xl px-4 py-3.5 text-[0.844rem]"
      style={{
        background: "color-mix(in srgb, var(--err) 10%, transparent)",
        border: "1px solid color-mix(in srgb, var(--err) 25%, transparent)",
        color: "var(--err)",
      }}
    >
      <p className="m-0 font-medium">{title}</p>
      <p className="m-0 mt-1">{summary}</p>
      {detail && (
        <p
          className="m-0 mt-2 overflow-x-auto font-mono text-[0.75rem] leading-[1.5] opacity-80"
          data-testid="agent-error-detail"
        >
          {detail}
        </p>
      )}
    </div>
  );
}

export function AgentHealthErrorBanner({ reason }: { reason: string }) {
  return (
    <div
      role="alert"
      data-testid="agent-health-banner"
      className="mb-6 rounded-xl px-4 py-3 text-[0.844rem]"
      style={{
        background: "color-mix(in srgb, var(--err) 10%, transparent)",
        border: "1px solid color-mix(in srgb, var(--err) 25%, transparent)",
        color: "var(--err)",
      }}
    >
      <span className="font-medium">Error: </span>
      {reason}
    </div>
  );
}
