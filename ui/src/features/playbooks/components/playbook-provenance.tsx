"use client";

import { BookOpenCheck } from "lucide-react";

import { formatDate } from "@/shared/date";

import { useOrganizationPlaybookRuns } from "../hooks/use-organization-playbook-runs";
import { PlaybookInstallActions } from "./playbook-install-actions";

const REVIEW_CHECKLIST = [
  "Remove names of people, clients, or companies, and any details the model kept by mistake.",
  "Check that each procedure, command, and standard is still how you want Agents to work.",
  "Resolve or delete the open questions at the end.",
  "Publishing makes this Skill visible to every member of the Organization.",
];

/**
 * Where a playbook's content came from, and what to check before publishing it.
 * Renders nothing for Skills no Playbook Extraction wrote, or for people who cannot manage Skills.
 */
export function PlaybookProvenance({
  skillId,
  skillName,
  publishedVersion,
  enabled,
  hasDraft,
}: {
  skillId: string;
  skillName: string;
  /** The latest published version, which the install actions offer; null before the first publish. */
  publishedVersion: number | null;
  enabled: boolean;
  hasDraft: boolean;
}) {
  const { runs } = useOrganizationPlaybookRuns(skillId, enabled);
  const latest = runs.find((run) => run.status === "SUCCEEDED");
  if (!enabled || !latest) return null;

  return (
    <section
      className="af-card mb-6 p-4"
      aria-label="Playbook source"
      style={{ borderColor: "color-mix(in srgb, var(--accent) 35%, var(--line))" }}
    >
      <div className="flex items-start gap-3">
        <BookOpenCheck size={18} className="mt-0.5 shrink-0" style={{ color: "var(--accent-ink)" }} aria-hidden />
        <div className="min-w-0 text-[0.84rem]">
          <p className="m-0 font-medium">
            Playbook extracted from {latest.sourceAgentName} on {formatDate(latest.finishedAt ?? latest.createdAt)}
          </p>
          <p className="mb-0 mt-1" style={{ color: "var(--ink-3)" }}>
            {latest.sessionCount} conversations from {formatDate(latest.windowStart)} to {formatDate(latest.windowEnd)}
            {latest.memoryCount > 0 ? `, and ${latest.memoryCount} long-term memories` : ""}.
          </p>
          {publishedVersion !== null && (
            <>
              <p className="mb-0 mt-3 font-medium">Put version {publishedVersion} to work</p>
              <PlaybookInstallActions skillId={skillId} skillName={skillName} version={publishedVersion} />
            </>
          )}
          {hasDraft && (
            <>
              <p className="mb-1 mt-3 font-medium">Before publishing the draft</p>
              <ul className="m-0 pl-5" style={{ color: "var(--ink-3)" }}>
                {REVIEW_CHECKLIST.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
