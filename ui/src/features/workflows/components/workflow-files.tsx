"use client";

import { useArtifactDownload } from "@/features/artifacts/hooks/use-artifacts";
import { ArtifactCard } from "@/features/artifacts/components/artifact-card";
import type { WorkflowFile } from "../run-schemas";

export const FILES_GONE =
  "This run’s agent was deleted, so its files can no longer be downloaded.";

export function WorkflowFiles({
  agentId,
  title,
  files,
  description,
  unavailable = false,
}: {
  agentId: string;
  title: string;
  files: WorkflowFile[];
  description?: string | null;
  /** The Agent was deleted, and its files with it: they are named but not offered. */
  unavailable?: boolean;
}) {
  const download = useArtifactDownload(agentId);
  if (!files.length) return null;
  return (
    <section aria-label={title} className="space-y-3 border-t border-[var(--line)] px-6 py-5">
      <h4 className="font-semibold">{title}</h4>
      {description && (
        <p className="text-sm text-[var(--ink-3)]">{description}</p>
      )}
      {unavailable && (
        <p className="text-sm text-[var(--ink-3)]">{FILES_GONE}</p>
      )}
      <ul className="space-y-3">
        {files.map((file) => (
          <li key={file.artifactId}>
            <ArtifactCard
              file={file}
              onDownload={
                unavailable ? undefined : () => download.mutate(file.artifactId)
              }
              disabled={download.isPending}
              downloading={
                download.isPending && download.variables === file.artifactId
              }
              error={
                download.variables === file.artifactId
                  ? download.error
                  : undefined
              }
            />
          </li>
        ))}
      </ul>
    </section>
  );
}
