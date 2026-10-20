"use client";

import { type WorkflowProblem } from "../validation";

/** Save or archive failure: links each problem to its section and offers conflict recovery. */
export function WorkflowSaveAlert({
  message,
  problems,
  onSelect,
  onLoadCurrent,
}: {
  message: string;
  problems: WorkflowProblem[];
  onSelect: (section: string) => void;
  /** Present after a revision conflict. */
  onLoadCurrent?: () => void;
}) {
  return (
    <div
      role="alert"
      aria-label="Workflow error"
      className="af-card p-5 mb-5 whitespace-pre-wrap"
      style={{ color: "var(--err)" }}
    >
      {message}
      {problems.length > 0 && (
        <ul className="mt-3 space-y-2">
          {problems.map((problem, index) => (
            <li key={index}>
              <button
                className="text-left underline underline-offset-4"
                onClick={() => onSelect(problem.section)}
              >
                {problem.label}: {problem.message}
              </button>
            </li>
          ))}
        </ul>
      )}
      {onLoadCurrent && (
        <button className="af-btn mt-3" onClick={onLoadCurrent}>
          Load current revision and keep my edits
        </button>
      )}
    </div>
  );
}
