"use client";

import { useState } from "react";
import { AppErrorState } from "@/components/app-error-state";
import { Button } from "@/components/ui/button";
import { useArtifacts } from "../hooks/use-artifacts";
import type { Artifact } from "../schemas";

function provenance(file: Artifact) {
  if (file.source === "workflow") return `Workflow run ${file.runId?.slice(0, 8)} · attempt ${file.attemptId?.slice(0, 8) ?? "unknown"}`;
  return file.source === "human" ? "Uploaded by a person" : "Chat";
}

export function AgentFiles({ agentId, runId, stepId, polling = false }: {
  agentId: string;
  runId?: string;
  stepId?: string;
  polling?: boolean;
}) {
  const [page, setPage] = useState(1);
  const { files, download } = useArtifacts(agentId, page, runId, stepId, polling);
  if (files.error) return (
    <AppErrorState error={files.error} title="Files are unavailable" onRetry={() => void files.refetch()} />
  );
  if (!files.data) return <p role="status">Loading files…</p>;
  const label = stepId ? "Step files" : runId ? "Run files" : "Agent files";
  return (
    <section aria-label={label} className="mt-4 space-y-4">
      <h3 className="font-semibold">Files</h3>
      {download.error && (
        <AppErrorState
          error={download.error}
          title="Download is unavailable"
          onRetry={() => download.variables && download.mutate(download.variables)}
        />
      )}
      {files.data.items.length === 0 && (
        <p className="text-sm text-[var(--ink-3)]">No published files yet.</p>
      )}
      <ul className="space-y-2">
        {files.data.items.map(file => (
          <li key={file.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[var(--line)] p-4">
            <div className="min-w-0">
              <p className="break-all font-medium">{file.filename}</p>
              <p className="text-xs text-[var(--ink-3)]">
                {file.size.toLocaleString()} bytes · {file.contentType} · {provenance(file)}
              </p>
              <p className="break-all text-xs text-[var(--ink-3)]">SHA-256: {file.checksum}</p>
            </div>
            <Button
              variant="outline"
              disabled={download.isPending}
              onClick={() => download.mutate(file.id)}
              aria-label={`Download ${file.filename}`}
            >Download</Button>
          </li>
        ))}
      </ul>
      {files.data.total > files.data.pageSize && (
        <div className="flex items-center gap-2">
          <Button variant="outline" disabled={page === 1} onClick={() => setPage(page - 1)}>Previous files</Button>
          <span>Page {page}</span>
          <Button
            variant="outline"
            disabled={page * files.data.pageSize >= files.data.total}
            onClick={() => setPage(page + 1)}
          >Next files</Button>
        </div>
      )}
      <p className="text-xs text-[var(--ink-3)]">
        Downloads use a fresh link valid for 15 minutes. Anyone with the link can download until it expires.
      </p>
    </section>
  );
}
