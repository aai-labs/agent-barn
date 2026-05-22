import { Page } from "@playwright/test";

export const MOCK_AGENT_ID = "33333333-3333-4333-8333-333333333333";
export const MOCK_TEMPLATE_ID = "44444444-4444-4444-8444-444444444444";
export const MOCK_ORG_ID = "22222222-2222-4222-8222-222222222222";

export const mockAgent = {
  id: MOCK_AGENT_ID,
  name: "Maya",
  status: "RUNNING",
  organization_id: MOCK_ORG_ID,
  template_id: MOCK_TEMPLATE_ID,
  template_version: 1,
  model: "litellm/gpt-5-mini",
  slack_channel_ids: [],
  slack_dm_user_ids: [],
  slack_group_policy: "allowlist",
  slack_dm_policy: "off",
  created_at: "2026-03-14T00:00:00Z",
  updated_at: "2026-05-14T09:14:00Z",
};

export const mockToolCall = {
  id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  agent_id: MOCK_AGENT_ID,
  session_id: "session-abc",
  tool_name: "read",
  arguments: { path: "/repo/config.yaml" },
  result: [{ type: "text", text: "db_host: postgres" }],
  status: "SUCCESS",
  occurred_at: "2026-05-21T10:00:00Z",
  completed_at: "2026-05-21T10:00:01Z",
  duration_ms: 1000,
};

export const mockAgentTemplate = {
  id: MOCK_TEMPLATE_ID,
  organization_id: MOCK_ORG_ID,
  version: 1,
  soul_md: "# Soul\nYou are a helpful assistant.",
  identity_md: "# Identity\nYou are an AI embedded in Slack.",
  user_md: "# Users\nTeam members.",
  tools_md: "# Tools\n- slack",
  agents_md: "",
  boot_md: "",
  bootstrap_md: "",
  heartbeat_md: "",
  created_at: "2026-03-14T00:00:00Z",
  updated_at: "2026-05-14T09:14:00Z",
};

export class AgentDataSupport {
  constructor(private page: Page) {}

  async interceptGetAgentsRequest({
    status = 200,
    detail = "Unable to load agents",
    body,
  }: {
    status?: number;
    detail?: string;
    body?: unknown;
  } = {}) {
    await this.page.route("**/api/v1/agents*", async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      const url = new URL(route.request().url());
      if (url.pathname !== "/api/v1/agents") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(
          status >= 400
            ? { detail }
            : (body ?? {
                page: 1,
                page_size: 50,
                total: 1,
                items: [mockAgent],
              }),
        ),
      });
    });
  }

  async interceptGetAgentRequest({
    agentId = MOCK_AGENT_ID,
    status = 200,
    detail = "Unable to load agent",
    body,
  }: {
    agentId?: string;
    status?: number;
    detail?: string;
    body?: unknown;
  } = {}) {
    await this.page.route(`**/api/v1/agents/${agentId}`, async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(
          status >= 400 ? { detail } : (body ?? { ...mockAgent, id: agentId }),
        ),
      });
    });
  }

  async interceptGetAgentTemplateRequest({
    agentId = MOCK_AGENT_ID,
    version = 1,
    status = 200,
    detail = "Unable to load template",
    body,
  }: {
    agentId?: string;
    version?: number;
    status?: number;
    detail?: string;
    body?: unknown;
  } = {}) {
    await this.page.route(
      `**/api/v1/agents/${agentId}/template/${version}`,
      async (route) => {
        if (route.request().method() !== "GET") {
          await route.fallback();
          return;
        }
        await route.fulfill({
          status,
          contentType: "application/json",
          body: JSON.stringify(
            status >= 400 ? { detail } : (body ?? mockAgentTemplate),
          ),
        });
      },
    );
  }

  async interceptCreateAgentRequest({
    status = 201,
    detail = "Unable to create agent",
    body,
  }: {
    status?: number;
    detail?: string;
    body?: unknown;
  } = {}) {
    await this.page.route("**/api/v1/agents", async (route) => {
      if (route.request().method() !== "POST") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(status >= 400 ? { detail } : (body ?? mockAgent)),
      });
    });
  }

  async interceptDeleteAgentRequest({
    agentId = MOCK_AGENT_ID,
    status = 204,
    detail = "Unable to delete agent",
  }: {
    agentId?: string;
    status?: number;
    detail?: string;
  } = {}) {
    await this.page.route(`**/api/v1/agents/${agentId}`, async (route) => {
      if (route.request().method() !== "DELETE") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status,
        contentType: "application/json",
        body: status >= 400 ? JSON.stringify({ detail }) : "",
      });
    });
  }

  async interceptStartAgentRequest({
    agentId = MOCK_AGENT_ID,
    status = 200,
    detail = "Unable to start agent",
    body,
  }: {
    agentId?: string;
    status?: number;
    detail?: string;
    body?: unknown;
  } = {}) {
    await this.page.route(
      `**/api/v1/agents/${agentId}/start`,
      async (route) => {
        if (route.request().method() !== "POST") {
          await route.fallback();
          return;
        }
        await route.fulfill({
          status,
          contentType: "application/json",
          body: JSON.stringify(
            status >= 400
              ? { detail }
              : (body ?? { ...mockAgent, id: agentId, status: "RUNNING" }),
          ),
        });
      },
    );
  }

  async interceptStopAgentRequest({
    agentId = MOCK_AGENT_ID,
    status = 200,
    detail = "Unable to stop agent",
    body,
  }: {
    agentId?: string;
    status?: number;
    detail?: string;
    body?: unknown;
  } = {}) {
    await this.page.route(
      `**/api/v1/agents/${agentId}/stop`,
      async (route) => {
        if (route.request().method() !== "POST") {
          await route.fallback();
          return;
        }
        await route.fulfill({
          status,
          contentType: "application/json",
          body: JSON.stringify(
            status >= 400
              ? { detail }
              : (body ?? { ...mockAgent, id: agentId, status: "STOPPED" }),
          ),
        });
      },
    );
  }

  async interceptPairAgentRequest({
    agentId = MOCK_AGENT_ID,
    status = 200,
    detail = "Unable to pair agent",
    message = "Agent paired successfully",
  }: {
    agentId?: string;
    status?: number;
    detail?: string;
    message?: string;
  } = {}) {
    await this.page.route(
      `**/api/v1/agents/${agentId}/pair`,
      async (route) => {
        if (route.request().method() !== "POST") {
          await route.fallback();
          return;
        }
        await route.fulfill({
          status,
          contentType: "application/json",
          body: JSON.stringify(status >= 400 ? { detail } : { message }),
        });
      },
    );
  }

  async interceptGetToolCallsRequest({
    agentId = MOCK_AGENT_ID,
    status = 200,
    detail = "Unable to load tool calls",
    body,
  }: {
    agentId?: string;
    status?: number;
    detail?: string;
    body?: unknown;
  } = {}) {
    await this.page.route(
      `**/api/v1/agents/${agentId}/tool-calls*`,
      async (route) => {
        if (route.request().method() !== "GET") {
          await route.fallback();
          return;
        }
        await route.fulfill({
          status,
          contentType: "application/json",
          body: JSON.stringify(
            status >= 400
              ? { detail }
              : (body ?? {
                  page: 1,
                  page_size: 20,
                  total: 1,
                  items: [mockToolCall],
                }),
          ),
        });
      },
    );
  }
}
