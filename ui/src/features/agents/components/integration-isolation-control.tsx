"use client";

import type { Agent, AgentSecretRead } from "../schemas";

export function IntegrationIsolationControl({ agent, secret, isolated, onChange }: {
  agent: Agent;
  secret: AgentSecretRead;
  isolated: boolean;
  onChange: (isolated: boolean) => void;
}) {
  const policy = secret.isolation;
  if (!policy) return null;
  const canEdit = agent.allowedActions.includes("agent.update") && agent.allowedActions.includes("agent.secret.manage");
  const needsRestart = agent.status === "RUNNING" || agent.status === "ERROR";
  const disabled = !policy.switchAvailable || !canEdit || (needsRestart && !agent.allowedActions.includes("agent.lifecycle.manage"));
  return (
    <div className="flex flex-col gap-2 border-t pt-3" style={{ borderColor: "var(--line)" }}>
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm font-medium">Credential isolation</span>
        <button type="button" role="switch" aria-label={`${secret.secretName} isolation`} aria-checked={isolated}
          disabled={disabled} onClick={() => onChange(!isolated)}
          className="relative h-5 w-9 shrink-0 rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-50"
          style={{ backgroundColor: isolated ? "var(--ink)" : "var(--line)" }}>
          <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${isolated ? "left-0.5 translate-x-4" : "left-0.5"}`} />
        </button>
      </div>
      <p className="m-0 text-xs" style={{ color: "var(--ink-3)" }}>{isolated ? policy.isolatedDescription : policy.directDescription}</p>
      <p className="m-0 text-xs" style={{ color: "var(--ink-4)" }}>Saved when you apply this setup.{needsRestart && " Applying restarts the Agent."}</p>
      <p className="m-0 text-xs" style={{ color: "var(--ink-4)" }}>
        {policy.applied == null ? "Runtime mode has not been verified." : `Current runtime: ${policy.applied ? "isolated" : "direct"}.`}
        {policy.pending && policy.applied != null && " Pending application on start."}
        {agent.status === "RUNNING" && policy.applied == null && policy.generation != null && " Waiting for startup."}
      </p>
      {policy.reconnectRequired && <p role="alert" className="m-0 text-xs" style={{ color: "var(--err)" }}>Reconnect SharePoint before retrying this mode.</p>}
      {agent.status === "ERROR" && !disabled && policy.lastVerified != null && policy.lastVerified !== isolated && (
        <button type="button" className="af-btn af-btn-sm self-start" onClick={() => onChange(policy.lastVerified!)}>Restore previous mode</button>
      )}
    </div>
  );
}
