"use client";

import { useArtifactDownload } from "@/features/artifacts/hooks/use-artifacts";
import { ArtifactCard } from "@/features/artifacts/components/artifact-card";
import type { WorkflowFile } from "../run-schemas";

export function WorkflowFiles({
  agentId,
  title,
  files,
  description,
}: {
  agentId: string;
  title: string;
  files: WorkflowFile[];
  description?: string | null;
}) {
  const download = useArtifactDownload(agentId);
  if (!files.length) return null;
  return (
    <section aria-label={title} className="space-y-3 border-t border-[var(--line)] px-6 py-5">
      <h4 className="font-semibold">{title}</h4>
      {description && (
        <p className="text-sm text-[var(--ink-3)]">{description}</p>
      )}
      <ul className="space-y-3">
        {files.map((file) => (
          <li key={file.artifactId}>
            <ArtifactCard
              file={file}
              onDownload={() => download.mutate(file.artifactId)}
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
