import { mockAgent } from "../pages/data-support/agent-data-support.po";

export const agentListWithMetadata = {
  page: 1,
  page_size: 50,
  total: 3,
  items: [
    mockAgent,
    {
      ...mockAgent,
      id: "44444444-4444-4444-8444-444444444444",
      name: "Karl the Assistant with a longer name",
      creator: null,
      last_message_at: null,
      last_activity_at: null,
      pending_model: "a-provider/a-longer-model-name-that-will-switch-on-restart",
    },
    {
      ...mockAgent,
      id: "55555555-5555-4555-8555-555555555555",
      name: "Read-only metadata",
      allowed_actions: ["agent.read"],
      creator: { ...mockAgent.creator, full_name: null },
      last_message_at: null,
      last_activity_at: null,
    },
  ],
};

export const agentListWithoutMetadata = {
  page: 1,
  page_size: 50,
  total: 1,
  items: [{ ...mockAgent, creator: undefined, last_message_at: undefined, last_activity_at: undefined }],
};

export const agentListWithPollingStates = {
  ...agentListWithMetadata,
  items: agentListWithMetadata.items.map((agent, index) => ({
    ...agent,
    status: index === 1 ? "STOPPED" : "RUNNING",
  })),
};
