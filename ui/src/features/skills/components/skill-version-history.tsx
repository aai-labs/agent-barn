import { History as HistoryIcon, RotateCcw } from "lucide-react";

import { Badge } from "@/components/badge";

import type { SkillVersion } from "../schemas";

interface SkillVersionHistoryProps {
  versions: SkillVersion[];
  isLoading: boolean;
  canManage: boolean;
  hasDraft: boolean;
  onRestore: (version: number) => void;
  restoringVersion: number | null;
}

export function SkillVersionHistory({
  versions,
  isLoading,
  canManage,
  hasDraft,
  onRestore,
  restoringVersion,
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
                {v.restoredFromVersion !== null && (
                  <Badge>Restored from v{v.restoredFromVersion}</Badge>
                )}
              </div>
              <div className="text-[12px] mt-0.5" style={{ color: "var(--ink-3)" }}>
                {new Date(v.createdAt).toLocaleString()}
              </div>
            </div>
            {canManage && !isCurrent && (
              <button
                type="button"
                className="af-btn af-btn-sm flex-shrink-0"
                disabled={hasDraft || restoringVersion !== null}
                title={hasDraft ? "Discard the in-progress draft before restoring another version" : undefined}
                onClick={() => onRestore(v.version)}
              >
                <RotateCcw size={13} />
                {restoringVersion === v.version ? "Restoring…" : "Restore as draft"}
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}
