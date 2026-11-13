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
  review_destination: "web",
};
export const WORKFLOW_CREATOR = {
  membership_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
  user_id: null as string | null,
  name: "Dana Creator",
};
/** A saved Organization workflow; `defaultAgentId` is the Agent its runs start with. */
export function workflowFixture(defaultAgentId: string | null = null, viewer = false) {
  return {
    id: WORKFLOW_ID,
    created_by: WORKFLOW_CREATOR as typeof WORKFLOW_CREATOR | null,
    default_agent_id: defaultAgentId,
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
export function workflowSummary(workflow: ReturnType<typeof workflowFixture>, runCount = 0) {
  const { draft, ...version } = workflow.version;
  return {
    ...workflow,
    default_agent_name: workflow.default_agent_id ? "Maya" : null,
    run_count: runCount,
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
export function workflowPaginationFixtures() {
  return ["Account briefs", "Lead review"].map((name, index) => {
    const workflow = workflowFixture();
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
