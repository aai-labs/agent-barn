import type { Page } from "@playwright/test";

import { TEST_ORG_ID } from "../../constants";
import { MOCK_AGENT_ID, mockAgent } from "./agent-data-support.po";
import { DataSupport } from "./data-support.po";

export class IntegrationSetupDataSupport {
  readonly requests: Record<string, unknown>[] = [];
  readonly lifecycleRequests: string[] = [];

  constructor(private page: Page) {}

  async open({ running = true, reject = true } = {}) {
    const data = new DataSupport(this.page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.users.interceptGetOrganizationsRequest();
    await data.agents.interceptGetAgentConfigurationRequest();
    await data.agents.interceptGetCustomApiConnectionsRequest();
    await data.agents.interceptGetAgentHealthRequest();
    await data.organizations.interceptGetOrganizationLlmBudget({ organizationId: TEST_ORG_ID });
    let agent = { ...mockAgent, status: running ? "RUNNING" : "STOPPED" };
    for (const action of ["stop", "start"]) {
      await this.page.route(`**/api/v1/organizations/*/agents/${MOCK_AGENT_ID}/${action}`, (route) => {
        this.lifecycleRequests.push(action);
        agent = { ...agent, status: action === "stop" ? "STOPPED" : "RUNNING" };
        return route.fulfill({ json: agent });
      });
    }
    const save = async (route: import("@playwright/test").Route) => {
      const body = route.request().postDataJSON();
      this.requests.push(body);
      const apollo = body.secrets?.find((secret: { provider: string }) => secret.provider === "apollo");
      if (reject && apollo?.content?.api_token !== "accepted-key") {
        return route.fulfill({ status: 400, json: { detail: {
          code: "INTEGRATION_VALIDATION_FAILED", provider: "apollo", message: "Apollo credential: Invalid API key",
        } } });
      }
      agent = { ...agent, status: body.restart ? "RUNNING" : "STOPPED" };
      return route.fulfill({ json: agent });
    };
    await this.page.route(`**/api/v1/organizations/*/agents/${MOCK_AGENT_ID}`, (route) => {
      return route.request().method() === "PATCH" ? save(route) : route.fulfill({ json: agent });
    });
    await this.page.goto(`/dashboard/${TEST_ORG_ID}/agents/${MOCK_AGENT_ID}/configuration?section=keys`);
  }
}
