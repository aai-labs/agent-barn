export const WORKFLOW_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
export const workflowDraft = {
  schema_version: 1,
  name: "Weekly pipeline report",
  description: "Summarize weekly pipeline changes",
  steps: [
    {
      id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
      name: "Read pipeline",
      goal: "Read this week's pipeline",
      completion_criteria: "Pipeline records are collected",
      artifact_description: "Source data",
      required_capabilities: ["reasoning"],
    },
    {
      id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
      name: "Prepare summary",
      goal: "Summarize changes and risks",
      completion_criteria: "Changes and risks are covered",
      artifact_description: null,
      required_capabilities: ["reasoning"],
    },
  ],
  inputs: [
    {
      key: "period",
      label: "Reporting period",
      description: "Period to summarize",
      type: "text",
      required: true,
    },
  ],
  final_artifact_description: "Weekly Markdown summary",
  review_destination: "web",
};
export function workflowFixture(agentId: string, viewer = false) {
  return {
    id: WORKFLOW_ID,
    agent_id: agentId,
    revision: 1,
    archived_at: null as string | null,
    version: {
      id: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
      number: 1,
      created_at: "2026-10-14T10:00:00Z",
      created_by_user_id: null,
      draft: structuredClone(workflowDraft),
    },
    allowed_actions: viewer ? [] : ["save_version", "archive"],
    execution_available: false,
  };
}

/** The list endpoint's card projection of a definition fixture. */
export function workflowSummary(workflow: ReturnType<typeof workflowFixture>) {
  const { draft, ...version } = workflow.version;
  return {
    ...workflow,
    version: {
      ...version,
      name: draft.name,
      description: draft.description,
      step_count: draft.steps.length,
      input_count: draft.inputs.length,
    },
  };
}

/** Other definitions preceding the primary workflow in a multi-page list. */
export function workflowPaginationFixtures(agentId: string) {
  return ["Account briefs", "Lead review"].map((name, index) => {
    const workflow = workflowFixture(agentId);
    workflow.id = `${String(index + 1).padStart(8, "0")}-aaaa-4aaa-8aaa-aaaaaaaaaaaa`;
    workflow.version.id = `${String(index + 1).padStart(8, "0")}-eeee-4eee-8eee-eeeeeeeeeeee`;
    workflow.version.draft.name = name;
    return workflow;
  });
}

export function workflowHistoryFixtures(
  workflow: ReturnType<typeof workflowFixture>,
) {
  return Array.from({ length: workflow.version.number }, (_, index) => ({
    ...structuredClone(workflow.version),
    id: `${String(index + 1).padStart(8, "0")}-eeee-4eee-8eee-eeeeeeeeeeee`,
    number: workflow.version.number - index,
  }));
}
