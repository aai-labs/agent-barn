import { History as HistoryIcon, Trash2 } from "lucide-react";

import { Badge } from "@/components/badge";

import type { SkillVersion } from "../schemas";

interface SkillVersionHistoryProps {
  versions: SkillVersion[];
  currentVersion: number;
  isLoading: boolean;
  canManage: boolean;
  onDelete: (version: number) => void;
  deletingVersion: number | null;
}

export function SkillVersionHistory({
  versions,
  currentVersion,
  isLoading,
  canManage,
  onDelete,
  deletingVersion,
}: SkillVersionHistoryProps) {
  const latest = versions.length > 0 ? Math.max(...versions.map((v) => v.version)) : currentVersion;

  if (isLoading) {
    return (
      <div className="text-[13px]" style={{ color: "var(--ink-3)" }}>
        Loading version history…
      </div>
    );
  }

  if (versions.length === 0) {
    return (
      <div className="text-[13px]" style={{ color: "var(--ink-4)" }}>
        No version history yet.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {versions.map((v) => {
        const isCurrent = v.version === latest;
        // The last remaining version is never deletable; a version pinned by any
        // agent is never deletable (recover by re-pinning, not by deleting a
        // pinned snapshot).
        const deleteBlocked = versions.length <= 1 || v.isPinnedByAgent;
        const deleteTitle = deleteBlocked
          ? versions.length <= 1
            ? "A skill must keep at least one version"
            : "This version is pinned by an agent — re-pin the agent before deleting it"
          : undefined;
        return (
          <div
            key={v.version}
            className="flex items-center gap-3 rounded-xl px-4 py-3"
            style={{ border: "1px solid var(--line)", background: "var(--bg-elev)" }}
          >
            <div
              className="w-8 h-8 rounded-lg grid place-items-center flex-shrink-0"
              style={{ background: "var(--bg-soft)" }}
            >
              <HistoryIcon size={14} style={{ color: "var(--ink-4)" }} />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="font-medium text-[13.5px]" style={{ color: "var(--ink)" }}>
                  Version {v.version}
                </span>
                {isCurrent && <Badge variant="ok">Current</Badge>}
                {v.isPinnedByAgent && <Badge>Pinned by agent</Badge>}
              </div>
              <div className="text-[12px] mt-0.5" style={{ color: "var(--ink-3)" }}>
                {new Date(v.createdAt).toLocaleString()}
              </div>
            </div>
            {canManage && (
              <button
                type="button"
                className="af-btn af-btn-sm flex-shrink-0"
                style={{ borderColor: "var(--err)", color: "var(--err)" }}
                disabled={deleteBlocked || deletingVersion !== null}
                title={deleteTitle}
                aria-label={`Delete version ${v.version}`}
                onClick={() => onDelete(v.version)}
              >
                <Trash2 size={13} />
                {deletingVersion === v.version ? "Deleting…" : "Delete"}
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}
