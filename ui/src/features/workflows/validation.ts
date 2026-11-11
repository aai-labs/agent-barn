import { ApiError } from "@/shared/api/error/errors";

import { WorkflowDraftSchema, type WorkflowDraft } from "./schemas";

type ValidationIssue = { path: readonly PropertyKey[]; message: string };
export type WorkflowProblem = {
  section: string;
  label: string;
  message: string;
  /** Editor field that shows this problem inline; absent for whole-list problems. */
  field?: string;
};

const fieldLabels: Record<string, string> = {
  name: "Name",
  goal: "What should the Agent do?",
  completionCriteria: "When is this step complete?",
  completion_criteria: "When is this step complete?",
  artifactDescription: "Output from this step (optional)",
  artifact_description: "Output from this step (optional)",
  requiredCapabilities: "Required capabilities",
  required_capabilities: "Required capabilities",
  label: "Label",
  description: "Description",
  type: "Type",
  required: "Required",
};
const camel = (field: string) =>
  field.replace(/_([a-z])/g, (_, letter: string) => letter.toUpperCase());

/** Identifies an editor field; steps use their identity so reordering keeps feedback. */
export const stepField = (stepId: string, field: string) =>
  `step:${stepId}:${field}`;
export const inputField = (index: number, field: string) =>
  `input:${index}:${field}`;

function problem({ path, message }: ValidationIssue, draft: WorkflowDraft) {
  const start = path.findIndex((part) => part !== "body" && part !== "draft");
  const [scope, index, rawField] = path.slice(Math.max(0, start));
  // Input keys are derived from labels and never shown, so their problems belong to the label.
  const field =
    rawField === "key" ? "label" : rawField ? camel(String(rawField)) : "";
  if (scope === "steps" && typeof index === "number") {
    const step = draft.steps[index];
    return {
      section: step?.id ?? "details",
      label: `Step ${index + 1}${field ? ` · ${fieldLabels[field] ?? "Step details"}` : ""}`,
      message,
      field: step && field ? stepField(step.id, field) : undefined,
    };
  }
  if (scope === "inputs") {
    return typeof index === "number"
      ? {
          section: "inputs",
          label: `Input ${index + 1}${field ? ` · ${fieldLabels[field] ?? "Input details"}` : ""}`,
          message,
          field: field ? inputField(index, field) : undefined,
        }
      : { section: "inputs", label: "Required inputs", message };
  }
  if (scope === "reviewDestination" || scope === "review_destination")
    return { section: "outputs", label: "Review destination", message };
  if (scope === "name" || scope === "description")
    return {
      section: "details",
      label: scope === "name" ? "Workflow name" : "Description (optional)",
      message,
      field: scope,
    };
  return {
    section: "details",
    label: scope === "steps" ? "Steps" : "Workflow details",
    message,
  };
}

/** Maps issues to sections and visible labels, keeping one problem per field. */
export function workflowProblems(
  issues: ValidationIssue[],
  draft: WorkflowDraft,
): WorkflowProblem[] {
  const seen = new Set<string>();
  return issues
    .map((issue) => problem(issue, draft))
    .filter(({ field, label }) => {
      const identity = field ?? label;
      if (seen.has(identity)) return false;
      seen.add(identity);
      return true;
    });
}

/** Current client validation problems keyed by editor field, for inline feedback. */
export function workflowFieldErrors(draft: WorkflowDraft): Map<string, string> {
  const result = WorkflowDraftSchema.safeParse(draft);
  if (result.success) return new Map();
  return new Map(
    workflowProblems(result.error.issues, draft).flatMap(
      ({ field, message }) =>
        field ? [[field, message] as [string, string]] : [],
    ),
  );
}

const duplicateInputs = /Inputs (\d+) and (\d+) share the key/;

export function workflowApiProblems(
  error: unknown,
  draft: WorkflowDraft,
): WorkflowProblem[] {
  if (!(error instanceof ApiError) || error.status !== 422) return [];
  const details: unknown = error.details?.detail;
  if (!Array.isArray(details)) return [];
  const issues: ValidationIssue[] = [];
  for (const item of details) {
    if (
      !item ||
      !Array.isArray(item.loc) ||
      !item.loc.every(
        (part: unknown) => typeof part === "string" || typeof part === "number",
      ) ||
      typeof item.msg !== "string"
    )
      continue;
    const duplicate =
      item.loc.at(-1) === "inputs" && item.msg.match(duplicateInputs);
    if (duplicate) {
      issues.push({
        path: ["inputs", Number(duplicate[2]) - 1, "label"],
        message: `Matches input ${duplicate[1]}; use a distinct label`,
      });
      continue;
    }
    issues.push({
      path: item.loc,
      message:
        item.loc.includes("inputs") && item.loc.at(-1) === "key"
          ? "Edit the input label"
          : item.msg,
    });
  }
  return workflowProblems(issues, draft);
}
