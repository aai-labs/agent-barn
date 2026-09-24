"use client";

import type {
  Agent,
  AgentConfigurationVersion,
  RestorePointConfigManifest,
} from "../schemas";
import { diffConfigManifest, hasConfigChanges } from "./restore-point-utils";

export function RestorePointConfigDiff({
  manifest,
  agent,
  active,
}: {
  manifest: RestorePointConfigManifest;
  agent: Agent;
  active: AgentConfigurationVersion;
}) {
  const rows = diffConfigManifest(manifest, agent, active);
  const changed = hasConfigChanges(rows);

  return (
    <div
      className="mt-3 rounded-xl p-3"
      style={{ background: "var(--bg-soft)", border: "1px solid var(--line)" }}
    >
      <div className="mb-2 flex items-center justify-between gap-3">
        <span className="text-[0.78rem] font-semibold" style={{ color: "var(--ink-2)" }}>
          Captured configuration
        </span>
        <span className="text-[0.75rem]" style={{ color: "var(--ink-4)" }}>
          {changed
            ? "Differs from the Agent's configuration now"
            : "Matches the Agent's configuration now"}
        </span>
      </div>

      <dl className="m-0 grid gap-x-4 gap-y-1.5 sm:grid-cols-[8rem_minmax(0,1fr)_minmax(0,1fr)]">
        <div className="hidden sm:block" aria-hidden />
        <div
          className="hidden text-[0.7rem] font-semibold uppercase tracking-[0.08em] sm:block"
          style={{ color: "var(--ink-4)" }}
        >
          Captured
        </div>
        <div
          className="hidden text-[0.7rem] font-semibold uppercase tracking-[0.08em] sm:block"
          style={{ color: "var(--ink-4)" }}
        >
          Now
        </div>

        {rows.map((row) => (
          <div key={row.key} className="contents">
            <dt className="text-[0.8rem]" style={{ color: "var(--ink-3)" }}>
              {row.label}
            </dt>
            <dd
              className="m-0 text-[0.8rem]"
              style={{ color: row.changed ? "var(--ink)" : "var(--ink-3)" }}
            >
              <span className="sr-only">Captured: </span>
              {row.recorded}
            </dd>
            <dd
              className="m-0 text-[0.8rem]"
              style={{ color: row.changed ? "var(--ink)" : "var(--ink-3)" }}
            >
              <span className="sr-only">Now: </span>
              {row.changed ? row.current : <span style={{ color: "var(--ink-4)" }}>Unchanged</span>}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
