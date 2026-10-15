import type { Page } from "@playwright/test";

import { TEST_ORG_ID } from "../../constants";
import { mockCustomApiConnection } from "../../fixtures/custom-api";
import {
  MOCK_AGENT_ID,
  mockAgent,
  mockAgentAllowedActions,
} from "./agent-data-support.po";
import { DataSupport } from "./data-support.po";

export class CustomApiDataSupport {
  readonly requests: {
    method: string;
    body: Record<string, unknown> | null;
    url: string;
  }[] = [];

  readonly lifecycleRequests: string[] = [];

  constructor(private page: Page) {}

  async open(
    options: {
      running?: boolean;
      actions?: string[];
      updating?: boolean;
      empty?: boolean;
      fail?: boolean;
      loadError?: boolean;

    } = {},
  ) {
    const data = new DataSupport(this.page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.users.interceptGetOrganizationsRequest();
    await data.agents.interceptGetAgentConfigurationRequest();
    await data.agents.interceptGetAgentHealthRequest();
    await data.organizations.interceptGetOrganizationLlmBudget({
      organizationId: TEST_ORG_ID,
    });
    await data.agents.interceptGetAgentRequest({
      body: {
        ...mockAgent,
        status: options.running ? "RUNNING" : "STOPPED",
        allowed_actions: options.actions ?? mockAgentAllowedActions,
        update_in_progress: options.updating ?? false,
      },
    });
    for (const operation of ["stop", "start"]) {
      await this.page.route(`**/api/v1/organizations/*/agents/${MOCK_AGENT_ID}/${operation}`, (route) => {
        this.lifecycleRequests.push(operation);
        return route.fulfill({ json: { ...mockAgent, status: operation === "start" ? "RUNNING" : "STOPPED" } });
      });
    }
    let connections: Record<string, unknown>[] = options.empty
      ? []
      : [{ ...mockCustomApiConnection }];
    await this.page.route(
      `**/api/v1/organizations/*/agents/${MOCK_AGENT_ID}/custom-api-connections**`,
      async (route) => {
        const request = route.request();
        if (request.method() === "GET") {
          return route.fulfill(
            options.loadError
              ? { status: 503, json: { detail: "Connections unavailable" } }
              : { json: connections },
          );
        }
        const body = request.postData() ? request.postDataJSON() : null;
        this.requests.push({
          method: request.method(),
          body,
          url: request.url(),
        });
        if (options.fail)
          return route.fulfill({
            status: 422,
            json: { detail: "Invalid Custom API configuration" },
          });
        if (request.method() === "DELETE") {
          connections = connections.filter((connection) => !request.url().includes(String(connection.id)));
          return route.fulfill({ status: 204 });
        }
        const connection = {
          ...mockCustomApiConnection,
          ...body,
          id: request.url().endsWith("custom-api-connections") ? `55555555-5555-4555-8555-${String(this.requests.length).padStart(12, "0")}` : mockCustomApiConnection.id,
          slug: body.name.toLowerCase().replace(/\s+/g, "-"),
          auth_type: body.auth.type,
          auth_header_name: body.auth.header_name ?? null,
          pending_apply: !body.restart,
          headers: body.headers.map(
            (header: { secret: boolean; value?: string }) => ({
              ...header,
              value: header.secret ? null : (header.value ?? ""),
            }),
          ),
        };
        connections = [...connections.filter((saved) => saved.id !== connection.id), connection];
        return route.fulfill({
          status:
            request.method() === "POST" && !request.url().endsWith("/apply")
              ? 201
              : 200,
          json: connection,
        });
      },
    );
    await this.page.goto(
      `/dashboard/${TEST_ORG_ID}/agents/${MOCK_AGENT_ID}/configuration?section=keys`,
    );
  }
}
