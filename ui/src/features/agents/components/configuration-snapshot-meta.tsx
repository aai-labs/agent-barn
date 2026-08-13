import { formatDate } from "@/shared/date";

import {
  isConfigurationSnapshot,
  snapshotSourceDetails,
  type Snapshot,
} from "./agent-configuration-utils";

export function ConfigurationSnapshotMeta({
  snapshot,
}: {
  snapshot: Snapshot;
}) {
  const isConfig = isConfigurationSnapshot(snapshot);
  const source = snapshotSourceDetails(snapshot);
  const versionLabel = isConfig
    ? snapshot.pinType === "override"
      ? `Agent-owned override v${snapshot.version ?? "draft"}`
      : "Shared template version"
    : "Published template version";
  const contextLabel = isConfig ? "Agent configuration" : "Status";

  return (
    <div
      className="grid gap-x-5 gap-y-4 text-[0.78rem] sm:grid-cols-2 lg:grid-cols-3"
      style={{ color: "var(--ink-3)" }}
    >
      <div className="sm:col-span-2 lg:col-span-3">
        <div className="text-[0.68rem] font-semibold uppercase tracking-[0.08em]" style={{ color: "var(--ink-4)" }}>
          Source
        </div>
        <div className="mt-1 text-[0.82rem] font-medium" style={{ color: "var(--ink-2)" }}>
          {source.label}
        </div>
        <div className="mt-0.5 text-[0.74rem]">{source.explanation}</div>
      </div>
      <div>
        <div className="text-[0.68rem] font-semibold uppercase tracking-[0.08em]" style={{ color: "var(--ink-4)" }}>
          Template key
        </div>
        <code className="mt-1 block w-fit rounded bg-muted px-1.5 py-0.5 font-mono text-[0.74rem]" style={{ color: "var(--ink-2)" }}>
          {source.templateKey}
        </code>
        <div className="mt-0.5 text-[0.74rem]">Stable runtime identifier</div>
      </div>
      <div>
        <div className="text-[0.68rem] font-semibold uppercase tracking-[0.08em]" style={{ color: "var(--ink-4)" }}>
          Template version
        </div>
        <div className="mt-1 text-[0.82rem] font-medium" style={{ color: "var(--ink-2)" }}>
          v{source.templateVersion}
        </div>
      </div>
      <div>
        <div className="text-[0.68rem] font-semibold uppercase tracking-[0.08em]" style={{ color: "var(--ink-4)" }}>
          {contextLabel}
        </div>
        <div className="mt-1 text-[0.82rem] font-medium" style={{ color: "var(--ink-2)" }}>
          {versionLabel}
        </div>
      </div>
      <div>
        <div className="text-[0.68rem] font-semibold uppercase tracking-[0.08em]" style={{ color: "var(--ink-4)" }}>
          Published
        </div>
        <div className="mt-1 text-[0.82rem] font-medium" style={{ color: "var(--ink-2)" }}>
          {formatDate(snapshot.createdAt)}
        </div>
      </div>
      <div>
        <div className="text-[0.68rem] font-semibold uppercase tracking-[0.08em]" style={{ color: "var(--ink-4)" }}>
          Last updated
        </div>
        <div className="mt-1 text-[0.82rem] font-medium" style={{ color: "var(--ink-2)" }}>
          {formatDate(snapshot.updatedAt)}
        </div>
      </div>
    </div>
  );
}
