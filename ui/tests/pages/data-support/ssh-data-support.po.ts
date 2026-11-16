import type { Page } from "@playwright/test";

import { TEST_ORG_ID } from "../../constants";
import { sshCredential } from "../../fixtures/ssh";
import userContext from "../../fixtures/user-context.json";
import { MOCK_AGENT_ID, mockAgent } from "./agent-data-support.po";
import { DataSupport } from "./data-support.po";

export class SshDataSupport {
  readonly requests: Record<string, unknown>[] = [];
  readonly assignmentRequests: Record<string, unknown>[] = [];
  failure = "";
  private keys: (typeof sshCredential)[] = [];
  constructor(private page: Page) {}

  async setup({ member = false, assigned = false } = {}) {
    const data = new DataSupport(this.page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest({
      userContext: {
        ...userContext,
        is_platform_admin: false,
        organization_users: userContext.organization_users.map(
          (membership) => ({
            ...membership,
            role: member ? "MEMBER" : "OWNER",
          }),
        ),
      },
    });
    await data.users.interceptGetOrganizationsRequest();
    await data.organizations.interceptAgentSettings();
    await data.agents.interceptGetAgentConfigurationRequest();
    await data.agents.interceptGetAgentHealthRequest();
    await data.agents.interceptGetCustomApiConnectionsRequest();
    await data.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "RUNNING" },
    });
    this.keys = assigned ? [{ ...sshCredential }] : [];
    await this.page.route(
      `**/api/v1/organizations/${TEST_ORG_ID}/shared-credentials?*`,
      (route) =>
        route.fulfill({
          json: { items: [], total: 0, page: 1, page_size: 15 },
        }),
    );
    await this.page.route(
      `**/api/v1/organizations/${TEST_ORG_ID}/ssh-credentials**`,
      (route) => {
        if (route.request().method() === "GET")
          return route.fulfill({
            json: { items: this.keys, total: this.keys.length },
          });
        const body = route.request().postDataJSON();
        this.requests.push(body);
        if (this.failure)
          return route.fulfill({ status: 422, json: { detail: this.failure } });
        const saved = {
          ...sshCredential,
          ...body,
          public_key: sshCredential.public_key,
        };
        this.keys = [saved];
        return route.fulfill({ status: 201, json: saved });
      },
    );
    await this.page.route(
      `**/api/v1/organizations/${TEST_ORG_ID}/agents/${MOCK_AGENT_ID}/ssh-credentials`,
      (route) => {
        if (route.request().method() === "PUT") {
          this.assignmentRequests.push(route.request().postDataJSON());
          if (this.failure)
            return route.fulfill({
              status: 409,
              json: { detail: this.failure },
            });
        }
        return route.fulfill({
          json: {
            credentials: assigned ? [sshCredential] : [],
            revision: 1,
            applied_ids: assigned ? [sshCredential.id] : [],
            pending_apply: false,
            enabled: true,
            allowed_actions: member ? [] : ["manage"],
          },
        });
      },
    );
  }

  async openSettings() {
    await this.page.goto(
      `/dashboard/${TEST_ORG_ID}/settings?tab=shared-credentials`,
    );
  }
  async openAgent() {
    await this.page.goto(
      `/dashboard/${TEST_ORG_ID}/agents/${MOCK_AGENT_ID}/configuration?section=keys`,
    );
  }
}
