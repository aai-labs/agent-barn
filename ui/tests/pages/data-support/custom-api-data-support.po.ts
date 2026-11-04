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
  readonly savedConnectionId = mockCustomApiConnection.id;

  constructor(private page: Page) {}

  async open(
    options: {
      running?: boolean;
      failed?: boolean;
      actions?: string[];
      updating?: boolean;
      empty?: boolean;
      fail?: boolean;
      loadError?: boolean;
      failStartOnce?: boolean;
      withGithub?: boolean;

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
    const agent = {
      ...mockAgent,
      status: options.failed ? "ERROR" : options.running ? "RUNNING" : "STOPPED",
      allowed_actions: options.actions ?? mockAgentAllowedActions,
      update_in_progress: options.updating ?? false,
      secrets: options.withGithub ? [{ provider: "github", secret_name: "GitHub credential", isolation: {
        desired: false, applied: false, switch_available: true, supported_modes: ["direct", "isolated"],
        direct_description: "The Agent receives the GitHub credential.",
        isolated_description: "The GitHub credential stays outside the Agent.",
      } }] : [],
    };
    await data.agents.interceptGetAgentRequest({ body: agent });
    for (const operation of ["stop", "start"]) {
      await this.page.route(`**/api/v1/organizations/*/agents/${MOCK_AGENT_ID}/${operation}`, (route) => {
        this.lifecycleRequests.push(operation);
        return route.fulfill({ json: { ...mockAgent, status: operation === "start" ? "RUNNING" : "STOPPED" } });
      });
    }
    await this.page.route(`**/api/v1/organizations/*/agents/${MOCK_AGENT_ID}`, (route) => {
      if (route.request().method() !== "PATCH") return route.fallback();
      const body = route.request().postDataJSON();
      this.requests.push({ method: route.request().method(), body, url: route.request().url() });
      if (options.failStartOnce && this.requests.length === 1) {
        agent.status = "ERROR";
        agent.secrets = agent.secrets.map((secret) => ({ ...secret, isolation: { ...secret.isolation,
          desired: body.policies.find((policy: { provider: string }) => policy.provider === secret.provider)?.isolated ?? secret.isolation.desired,
        } }));
        connections = body.custom_api.creates.map((data: Record<string, unknown>) => ({ ...mockCustomApiConnection, ...data }));
        return route.fulfill({ status: 503, json: { detail: "The runtime could not start" } });
      }
      return route.fulfill(options.fail
        ? { status: 422, json: { detail: "Invalid Custom API configuration" } }
        : { json: { ...mockAgent, status: options.running ? "RUNNING" : "STOPPED" } });
    });
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
        if (request.url().endsWith("/preflight")) return route.fulfill({ status: 204 });
        if (request.url().endsWith("/apply") && Array.isArray(body.creates)) {
          connections = connections.filter((connection) => !body.deletes.includes(connection.id));
          const writes = [
            ...body.updates,
            ...body.creates.map((data: Record<string, unknown>, index: number) => ({
              id: `55555555-5555-4555-8555-${String(index + this.requests.length).padStart(12, "0")}`, data,
            })),
          ];
          for (const { id, data } of writes) {
            const previous = connections.find((connection) => connection.id === id);
            const connection = {
              ...mockCustomApiConnection, ...previous, ...data, id,
              slug: previous?.slug ?? data.name.toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^[-_]+|[-_]+$/g, ""),
              auth_type: data.auth.type, auth_header_name: data.auth.header_name ?? null, auth_token_url: data.auth.token_url ?? null, auth_scope: data.auth.scope ?? null,
              pending_apply: !body.restart,
              headers: data.headers.map((header: { secret: boolean; value?: string }) => ({
                ...header, value: header.secret ? null : (header.value ?? ""),
              })),
            };
            connections = [...connections.filter((saved) => saved.id !== id), connection];
          }
          return route.fulfill({ json: connections });
        }
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
          auth_token_url: body.auth.token_url ?? null,
          auth_scope: body.auth.scope ?? null,
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
