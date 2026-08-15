import { History as HistoryIcon, Trash2 } from "lucide-react";

import { Badge } from "@/components/badge";

import type { SkillVersion } from "../schemas";

interface SkillVersionHistoryProps {
  versions: SkillVersion[];
  isLoading: boolean;
  canManage: boolean;
  isAssigned: boolean;
  onDelete: (version: number) => void;
  deletingVersion: number | null;
}

export function SkillVersionHistory({
  versions,
  isLoading,
  canManage,
  isAssigned,
  onDelete,
  deletingVersion,
}: SkillVersionHistoryProps) {
  const latest = Math.max(0, ...versions.map((v) => v.version));

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
        // The currently published version is protected while agents are assigned;
        // the last remaining version is never deletable.
        const deleteBlocked = versions.length <= 1 || (isCurrent && isAssigned);
        const deleteTitle = deleteBlocked
          ? versions.length <= 1
            ? "A skill must keep at least one version"
            : "Unassign this skill from agents before deleting the current version"
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
