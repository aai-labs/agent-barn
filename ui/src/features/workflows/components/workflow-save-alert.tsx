"use client";

import { AlertCircle, ArrowRight } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

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
    <Alert
      variant="destructive"
      aria-label="Workflow error"
      className="mb-5 border-destructive/30 bg-destructive/5 p-4"
    >
      <AlertCircle className="size-5" aria-hidden="true" />
      <AlertTitle>{problems.length ? "Check these fields" : "Something went wrong"}</AlertTitle>
      <AlertDescription className="mt-1 whitespace-pre-wrap">
      {message}
      {problems.length > 0 && (
        <ul className="mt-3 space-y-2">
          {problems.map((problem, index) => (
            <li key={index}>
              <button
                className="inline-flex items-center gap-2 rounded-md text-left font-medium underline underline-offset-4 hover:no-underline focus-visible:outline-2 focus-visible:outline-offset-2"
                onClick={() => onSelect(problem.section)}
              >
                <ArrowRight className="size-4 shrink-0" aria-hidden="true" />
                <span>{problem.label}: {problem.message}</span>
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
      </AlertDescription>
    </Alert>
  );
}
