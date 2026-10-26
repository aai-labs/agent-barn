"use client";

import Link from "next/link";
import { ExternalLink } from "lucide-react";

import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import type { Agent } from "@/features/agents/schemas";
import { canAgent } from "@/features/agents/utils";
import { useActiveOrgRole } from "@/features/organizations/hooks/use-active-org-role";

import { useSetFileSync } from "../hooks/use-file-sync-actions";
import type { AgentFileSync } from "../schemas";
import { fileSyncSummary } from "../utils";

export function FileSyncStatusCard({ agent, fileSync }: { agent: Agent; fileSync: AgentFileSync }) {
  const setFileSync = useSetFileSync(agent.id);
  const { role, selectedOrganization } = useActiveOrgRole();
  const canConnect = role === "OWNER" || role === "ADMIN";
  const canSwitch = canAgent(agent, "agent.update");
  const summary = fileSyncSummary(fileSync, agent.status);

  return (
    <section className="af-card p-5" aria-label="File sync">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <h2 className="m-0 text-[14px] font-semibold" style={{ color: "var(--ink)" }}>
            File sync
          </h2>
          <p className="m-0 mt-2 text-[0.95rem] font-medium" style={{ color: "var(--ink)" }}>
            {summary.headline}
          </p>
          {summary.detail && (
            <p className="m-0 mt-1 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
              {summary.detail}
            </p>
          )}
          {fileSync.state === "not_connected" && (
            <p className="m-0 mt-1 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
              {canConnect && selectedOrganization ? (
                <>
                  Connect a storage provider in{" "}
                  <Link className="underline" href={`/dashboard/${selectedOrganization.id}/settings?tab=sync`}>
                    Organization settings
                  </Link>
                  .
                </>
              ) : (
                "An Owner or Admin can connect one in Organization settings."
              )}
            </p>
          )}
        </div>
        {fileSync.folderUrl && fileSync.provider && (
          <a
            className="af-btn af-btn-ghost af-btn-sm inline-flex items-center gap-1.5"
            href={fileSync.folderUrl}
            target="_blank"
            rel="noopener noreferrer"
          >
            Open in {fileSync.provider.displayName} <ExternalLink size={13} aria-hidden />
          </a>
        )}
      </div>

      {canSwitch && (
        <div className="mt-4 flex flex-col gap-1.5">
          <Label className="flex items-start gap-2 text-[0.84rem] font-medium" style={{ color: "var(--ink)" }}>
            <Checkbox
              className="mt-0.5"
              checked={fileSync.enabled}
              disabled={setFileSync.isPending}
              onCheckedChange={(checked) => setFileSync.mutate(checked === true)}
            />
            <span>Sync this agent&apos;s files</span>
          </Label>
          {setFileSync.error && (
            <span role="alert" className="text-xs" style={{ color: "var(--err)" }}>
              {setFileSync.error instanceof Error ? setFileSync.error.message : "Changing file sync failed."}
            </span>
          )}
        </div>
      )}
    </section>
  );
}
