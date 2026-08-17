import { Check } from "lucide-react";

import type { AgentOverrideVersion } from "../schemas";
import { ConfigurationSnapshotMeta } from "./configuration-snapshot-meta";

export function AgentConfigurationOverrideHistory({
  versions,
}: {
  versions: AgentOverrideVersion[];
}) {
  return (
    <section className="af-card p-5">
      <h2
        className="m-0 text-[1rem] font-semibold"
        style={{ color: "var(--ink)" }}
      >
        Published override history
      </h2>
      <div className="mt-4 divide-y" style={{ borderColor: "var(--line)" }}>
        {versions.map((version) => (
          <div
            key={version.id}
            className="flex flex-col gap-3 py-4 first:pt-0 last:pb-0"
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div
                  className="flex flex-wrap items-center gap-2 text-[0.86rem] font-medium"
                  style={{ color: "var(--ink-2)" }}
                >
                  <Check size={14} style={{ color: "var(--ok)" }} />
                  <span>Override v{version.version}</span>
                  <span
                    className="rounded-full px-1.5 py-0.5 text-[0.68rem] font-medium"
                    style={{
                      background: "color-mix(in srgb, var(--ok) 14%, transparent)",
                      color: "var(--ok)",
                    }}
                  >
                    Published
                  </span>
                </div>
                <p
                  className="mb-0 mt-1 text-[0.78rem]"
                  style={{ color: "var(--ink-3)" }}
                >
                  A private Agent-owned configuration based on the source template below.
                </p>
              </div>
              <div className="text-right text-[0.78rem]" style={{ color: "var(--ink-3)" }}>
                <span className="block font-semibold uppercase tracking-[0.06em]" style={{ color: "var(--ink-4)" }}>
                  Published by
                </span>
                <span className="mt-0.5 block" style={{ color: "var(--ink-2)" }}>
                  {version.author?.fullName ?? version.author?.email ?? "Unknown author"}
                </span>
                {version.author?.fullName && version.author.email && (
                  <span className="mt-0.5 block">{version.author.email}</span>
                )}
              </div>
            </div>
            <ConfigurationSnapshotMeta snapshot={version} />
          </div>
        ))}
      </div>
    </section>
  );
}
