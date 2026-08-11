import type { ReactNode } from "react";
import { LockKeyhole } from "lucide-react";

import type { Snapshot } from "./agent-configuration-utils";
import { ConfigurationArtifactSurface } from "./configuration-artifact-surface";
import { ConfigurationRequiredSkills } from "./configuration-required-skills";
import { ConfigurationSnapshotMeta } from "./configuration-snapshot-meta";

export function ConfigurationReadOnlySnapshot({
  snapshot,
  title,
  actions,
}: {
  snapshot: Snapshot;
  title: string;
  actions?: ReactNode;
}) {
  return (
    <section className="af-card overflow-hidden">
      <div
        className="flex flex-wrap items-start justify-between gap-3 border-b px-5 py-4"
        style={{ borderColor: "var(--line)" }}
      >
        <div>
          <div className="flex items-center gap-2">
            <LockKeyhole size={15} style={{ color: "var(--ink-3)" }} />
            <h2
              className="m-0 text-[1rem] font-semibold"
              style={{ color: "var(--ink)" }}
            >
              {title}
            </h2>
          </div>
          <div className="mt-1">
            <ConfigurationSnapshotMeta snapshot={snapshot} />
          </div>
        </div>
        {actions && <div className="flex gap-2">{actions}</div>}
      </div>
      <div className="p-5">
        <p
          className="mb-4 mt-0 text-[0.86rem]"
          style={{ color: "var(--ink-2)" }}
        >
          {snapshot.description || "No description"}
        </p>
        <ConfigurationArtifactSurface snapshot={snapshot} />
        <ConfigurationRequiredSkills snapshot={snapshot} />
      </div>
    </section>
  );
}
