import { Page } from "@playwright/test";

export const MOCK_AGENT_ID = "33333333-3333-4333-8333-333333333333";
export const MOCK_TEMPLATE_ID = "44444444-4444-4444-8444-444444444444";
export const MOCK_TEMPLATE_SLUG = "maya-3f9a2c1b";
export const MOCK_ORG_ID = "22222222-2222-4222-8222-222222222222";

export const MOCK_VIEWER_ROLE_ID = "77777777-0000-4000-8000-000000000001";
export const MOCK_EDITOR_ROLE_ID = "77777777-0000-4000-8000-000000000002";
export const MOCK_OWNER_ROLE_ID = "77777777-0000-4000-8000-000000000003";
export const MOCK_MEMBER_USER_ID = "88888888-8888-4888-8888-888888888888";
export const MOCK_ELIGIBLE_USER_ID = "99999999-9999-4999-8999-999999999999";

export const mockAccessRoles = [
  {
    id: MOCK_VIEWER_ROLE_ID,
    name: "VIEWER",
    permissions: ["agent.read", "activity.read", "cost.read"],
    is_locked: true,
  },
  {
    id: MOCK_EDITOR_ROLE_ID,
    name: "EDITOR",
    permissions: [
      "agent.read",
      "activity.read",
      "cost.read",
      "agent.update",
      "agent.lifecycle.manage",
      "agent.secret.manage",
    ],
    is_locked: true,
  },
  {
    id: MOCK_OWNER_ROLE_ID,
    name: "OWNER",
    permissions: [
      "agent.read",
      "activity.read",
      "cost.read",
      "agent.update",
      "agent.lifecycle.manage",
      "agent.secret.manage",
      "agent.delete",
      "agent.access.manage",
    ],
    is_locked: true,
  },
];

export const mockAssignedMember = {
  user_id: MOCK_MEMBER_USER_ID,
  email: "member@example.com",
  full_name: "Ada Lovelace",
  organization_role: "MEMBER",
  is_pending: false,
  is_creator: false,
  access_role: mockAccessRoles[0],
};

export const mockEligibleCandidate = {
  user_id: MOCK_ELIGIBLE_USER_ID,
  email: "grace@example.com",
  full_name: "Grace Hopper",
  organization_role: "MEMBER",
  is_pending: false,
  is_creator: false,
};

export const mockGeneralAccessRestricted = { role: null };
export const mockGeneralAccessAll = { role: mockAccessRoles[0] };

export const mockAgentAllowedActions = [
  "agent.read",
  "agent.update",
  "agent.delete",
  "agent.lifecycle.manage",
  "agent.access.manage",
  "agent.secret.manage",
  "activity.read",
  "cost.read",
];

export const mockAgent = {
  id: MOCK_AGENT_ID,
  name: "Maya",
  status: "RUNNING",
  platform: "slack",
  organization_id: MOCK_ORG_ID,
  template_slug: MOCK_TEMPLATE_SLUG,
  template_version: 1,
  model: "litellm/gpt-5-mini",
  approval_mode: "auto",
  slack_config: {
    channel_ids: [],
    dm_user_ids: [],
    group_policy: "allowlist",
    dm_policy: "off",
  },
  teams_config: null,
  secrets: [],
  skills: [],
  webhook_url: null,
  allowed_actions: mockAgentAllowedActions,
  created_at: "2026-03-14T00:00:00Z",
  updated_at: "2026-05-14T09:14:00Z",
};

export const mockSecret = {
  provider: "github",
  secret_name: "github-secret",
};

export const mockAssignedSkill = {
  id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
  name: "github",
  source: "aai_cli",
  required_providers: ["github"],
  tools_pointer: null,
  required: false,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
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
  template_slug: MOCK_TEMPLATE_SLUG,
  template_name: "Maya",
  template_source: "custom",
  version: 1,
  soul_md: "# Soul\nYou are a helpful assistant.",
  identity_md: "# Identity\nYou are an AI embedded in Slack.",
  user_md: "# Users\nTeam members.",
  tools_md: "# Tools\n- slack",
  agents_md: "",
  boot_md: "",
  bootstrap_md: "",
  heartbeat_md: "",
  required_skills: [],
  created_at: "2026-03-14T00:00:00Z",
  updated_at: "2026-05-14T09:14:00Z",
};

export const mockTemplates = [
  {
    ...mockAgentTemplate,
    id: "55555555-5555-4555-8555-555555555551",
    template_slug: "general-purpose",
    template_name: "General Purpose",
    template_source: "pre-defined",
  },
  {
    ...mockAgentTemplate,
    id: "55555555-5555-4555-8555-555555555552",
    template_slug: "scrum-master",
    template_name: "Scrum Master",
    template_source: "pre-defined",
    soul_md: "# SOUL.md - Who {{ agent_display_name }} Is\nScrum master soul.",
  },
  {
    ...mockAgentTemplate,
    id: "55555555-5555-4555-8555-555555555553",
    template_slug: "my-custom",
    template_name: "My Custom",
    template_source: "custom",
  },
];

// Two versions (latest first) for any lineage — used by version dropdowns.
export function mockVersionsForSlug(slug: string) {
  const base =
    mockTemplates.find((t) => t.template_slug === slug) ?? {
      ...mockAgentTemplate,
      template_slug: slug,
      template_name: slug,
    };
  return [
    {
      ...base,
      id: "66666666-6666-4666-8666-666666666602",
      version: 2,
      soul_md: `# Soul v2\n${base.soul_md}`,
    },
    {
      ...base,
      id: "66666666-6666-4666-8666-666666666601",
      version: 1,
      soul_md: `# Soul v1\n${base.soul_md}`,
    },
  ];
}

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

  async interceptGetAccessRolesRequest({
    status = 200,
    detail = "Unable to load access roles",
    body,
  }: {
    status?: number;
    detail?: string;
    body?: unknown;
  } = {}) {
    await this.page.route("**/api/v1/agents/access-roles", async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(status >= 400 ? { detail } : (body ?? mockAccessRoles)),
      });
    });
  }

  async interceptGetAgentAccessListRequest({
    agentId = MOCK_AGENT_ID,
    status = 200,
    detail = "Unable to load Agent access",
    body,
  }: {
    agentId?: string;
    status?: number;
    detail?: string;
    body?: unknown;
  } = {}) {
    await this.page.route(`**/api/v1/agents/${agentId}/access`, async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(
          status >= 400 ? { detail } : (body ?? [mockAssignedMember]),
        ),
      });
    });
  }

  async interceptGetEligibleAgentAccessRequest({
    agentId = MOCK_AGENT_ID,
    status = 200,
    detail = "Unable to load eligible Members",
    body,
  }: {
    agentId?: string;
    status?: number;
    detail?: string;
    body?: unknown;
  } = {}) {
    await this.page.route(
      `**/api/v1/agents/${agentId}/access/eligible*`,
      async (route) => {
        if (route.request().method() !== "GET") {
          await route.fallback();
          return;
        }
        const url = new URL(route.request().url());
        const search = url.searchParams.get("search")?.toLowerCase();
        let items = body ? (body as unknown[]) : [mockEligibleCandidate];
        if (search && !body) {
          items = items.filter((c) => {
            const candidate = c as typeof mockEligibleCandidate;
            return (
              candidate.full_name.toLowerCase().includes(search) ||
              candidate.email.toLowerCase().includes(search)
            );
          });
        }
        await route.fulfill({
          status,
          contentType: "application/json",
          body: JSON.stringify(status >= 400 ? { detail } : items),
        });
      },
    );
  }

  async interceptGrantAgentAccessRequest({
    agentId = MOCK_AGENT_ID,
    status = 201,
    detail = "Unable to grant access",
    body,
  }: {
    agentId?: string;
    status?: number;
    detail?: string;
    body?: unknown;
  } = {}) {
    await this.page.route(`**/api/v1/agents/${agentId}/access`, async (route) => {
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
            : (body ?? {
                ...mockEligibleCandidate,
                access_role: mockAccessRoles[0],
              }),
        ),
      });
    });
  }

  async interceptChangeAgentAccessRoleRequest({
    agentId = MOCK_AGENT_ID,
    userId = MOCK_MEMBER_USER_ID,
    status = 200,
    detail = "Unable to change access role",
    body,
  }: {
    agentId?: string;
    userId?: string;
    status?: number;
    detail?: string;
    body?: unknown;
  } = {}) {
    await this.page.route(
      `**/api/v1/agents/${agentId}/access/${userId}`,
      async (route) => {
        if (route.request().method() !== "PATCH") {
          await route.fallback();
          return;
        }
        await route.fulfill({
          status,
          contentType: "application/json",
          body: JSON.stringify(
            status >= 400
              ? { detail }
              : (body ?? { ...mockAssignedMember, access_role: mockAccessRoles[1] }),
          ),
        });
      },
    );
  }

  async interceptRevokeAgentAccessRequest({
    agentId = MOCK_AGENT_ID,
    userId = MOCK_MEMBER_USER_ID,
    status = 204,
    detail = "Unable to remove access",
  }: {
    agentId?: string;
    userId?: string;
    status?: number;
    detail?: string;
  } = {}) {
    await this.page.route(
      `**/api/v1/agents/${agentId}/access/${userId}`,
      async (route) => {
        if (route.request().method() !== "DELETE") {
          await route.fallback();
          return;
        }
        await route.fulfill({
          status,
          contentType: "application/json",
          body: status >= 400 ? JSON.stringify({ detail }) : "",
        });
      },
    );
  }

  async interceptGetGeneralAccessRequest({
    agentId = MOCK_AGENT_ID,
    status = 200,
    detail = "Unable to load General access",
    body,
  }: {
    agentId?: string;
    status?: number;
    detail?: string;
    body?: unknown;
  } = {}) {
    await this.page.route(
      `**/api/v1/agents/${agentId}/general-access`,
      async (route) => {
        if (route.request().method() !== "GET") {
          await route.fallback();
          return;
        }
        await route.fulfill({
          status,
          contentType: "application/json",
          body: JSON.stringify(
            status >= 400 ? { detail } : (body ?? mockGeneralAccessRestricted),
          ),
        });
      },
    );
  }

  async interceptSetGeneralAccessRequest({
    agentId = MOCK_AGENT_ID,
    status = 200,
    detail = "Unable to update General access",
    body,
  }: {
    agentId?: string;
    status?: number;
    detail?: string;
    body?: unknown;
  } = {}) {
    await this.page.route(
      `**/api/v1/agents/${agentId}/general-access`,
      async (route) => {
        if (route.request().method() !== "PUT") {
          await route.fallback();
          return;
        }
        await route.fulfill({
          status,
          contentType: "application/json",
          body: JSON.stringify(
            status >= 400 ? { detail } : (body ?? mockGeneralAccessAll),
          ),
        });
      },
    );
  }

  async interceptRemoveGeneralAccessRequest({
    agentId = MOCK_AGENT_ID,
    status = 204,
    detail = "Unable to update General access",
  }: {
    agentId?: string;
    status?: number;
    detail?: string;
  } = {}) {
    await this.page.route(
      `**/api/v1/agents/${agentId}/general-access`,
      async (route) => {
        if (route.request().method() !== "DELETE") {
          await route.fallback();
          return;
        }
        await route.fulfill({
          status,
          contentType: "application/json",
          body: status >= 400 ? JSON.stringify({ detail }) : "",
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

  async interceptUpdateAgentRequest({
    agentId = MOCK_AGENT_ID,
    status = 200,
    detail = "Unable to update agent",
    body,
  }: {
    agentId?: string;
    status?: number;
    detail?: string;
    body?: unknown;
  } = {}) {
    await this.page.route(`**/api/v1/agents/${agentId}`, async (route) => {
      if (route.request().method() !== "PATCH") {
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

  async interceptSlackChannelsRequest({
    agentId = MOCK_AGENT_ID,
    status = 200,
    body,
  }: {
    agentId?: string;
    status?: number;
    body?: unknown;
  } = {}) {
    await this.page.route(
      `**/api/v1/agents/${agentId}/slack/channels*`,
      async (route) => {
        if (route.request().method() !== "GET") {
          await route.fallback();
          return;
        }
        await route.fulfill({
          status,
          contentType: "application/json",
          body: JSON.stringify(
            body ?? [
              { id: "C001", name: "general" },
              { id: "C002", name: "engineering" },
            ],
          ),
        });
      },
    );
  }

  async interceptSlackUsersRequest({
    agentId = MOCK_AGENT_ID,
    status = 200,
    body,
  }: {
    agentId?: string;
    status?: number;
    body?: unknown;
  } = {}) {
    await this.page.route(
      `**/api/v1/agents/${agentId}/slack/users*`,
      async (route) => {
        if (route.request().method() !== "GET") {
          await route.fallback();
          return;
        }
        await route.fulfill({
          status,
          contentType: "application/json",
          body: JSON.stringify(
            body ?? [
              { id: "U001", name: "alice", real_name: "Alice Smith" },
              { id: "U002", name: "bob", real_name: "Bob Jones" },
            ],
          ),
        });
      },
    );
  }

  async interceptGetTemplatesRequest({
    status = 200,
    detail = "Unable to load templates",
    body,
  }: {
    status?: number;
    detail?: string;
    body?: unknown;
  } = {}) {
    await this.page.route("**/api/v1/templates*", async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      const url = new URL(route.request().url());
      if (url.pathname !== "/api/v1/templates") {
        await route.fallback();
        return;
      }
      // Apply search/source params so specs can assert filtering behavior.
      const search = url.searchParams.get("search")?.toLowerCase();
      const source = url.searchParams.get("source");
      let items = mockTemplates;
      if (search) {
        items = items.filter(
          (t) =>
            t.template_name.toLowerCase().includes(search) ||
            t.template_slug.toLowerCase().includes(search),
        );
      }
      if (source) {
        items = items.filter((t) => t.template_source === source);
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
                total: items.length,
                items,
              }),
        ),
      });
    });
  }

  async interceptGetTemplateRequest({
    slug = MOCK_TEMPLATE_SLUG,
    status = 200,
    detail = "Unable to load template",
    body,
  }: {
    slug?: string;
    status?: number;
    detail?: string;
    body?: unknown;
  } = {}) {
    await this.page.route(`**/api/v1/templates/${slug}`, async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      const fallback =
        mockTemplates.find((t) => t.template_slug === slug) ?? mockAgentTemplate;
      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(status >= 400 ? { detail } : (body ?? fallback)),
      });
    });
  }

  async interceptGetTemplateVersionsRequest({
    status = 200,
    detail = "Unable to load versions",
    body,
  }: {
    status?: number;
    detail?: string;
    body?: unknown;
  } = {}) {
    await this.page.route("**/api/v1/templates/*/versions", async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      const match = new URL(route.request().url()).pathname.match(
        /\/templates\/([^/]+)\/versions$/,
      );
      const slug = match ? match[1] : MOCK_TEMPLATE_SLUG;
      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(
          status >= 400 ? { detail } : (body ?? mockVersionsForSlug(slug)),
        ),
      });
    });
  }

  async interceptCreateTemplateRequest({
    status = 201,
    detail = "Unable to create template",
    body,
  }: {
    status?: number;
    detail?: string;
    body?: unknown;
  } = {}) {
    await this.page.route("**/api/v1/templates", async (route) => {
      if (route.request().method() !== "POST") {
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
    });
  }

  async interceptUpdateTemplateRequest({
    slug = MOCK_TEMPLATE_SLUG,
    status = 200,
    detail = "Unable to update template",
    body,
  }: {
    slug?: string;
    status?: number;
    detail?: string;
    body?: unknown;
  } = {}) {
    await this.page.route(`**/api/v1/templates/${slug}`, async (route) => {
      if (route.request().method() !== "PATCH") {
        await route.fallback();
        return;
      }
      const fallback =
        mockTemplates.find((t) => t.template_slug === slug) ?? mockAgentTemplate;
      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(
          status >= 400 ? { detail } : (body ?? { ...fallback, version: fallback.version + 1 }),
        ),
      });
    });
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

  async interceptValidateIntegrationRequest({
    agentId = MOCK_AGENT_ID,
    provider = "github",
    status = 404,
    detail = "Agent not found",
  }: {
    agentId?: string;
    provider?: string;
    status?: number;
    detail?: string;
  } = {}) {
    await this.page.route(
      `**/api/v1/agents/${agentId}/integrations/${provider}/validate`,
      async (route) => {
        if (route.request().method() !== "POST") {
          await route.fallback();
          return;
        }
        await route.fulfill({
          status,
          contentType: "application/json",
          body: JSON.stringify({ detail }),
        });
      },
    );
  }
}
