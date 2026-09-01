import { Page } from "@playwright/test";

import {
  COMMUNICATION_CONNECTION_ID,
  mockCommunicationConnection,
  mockCommunicationConnectionJournalPage,
  mockCommunicationConnectionSummary,
  mockCommunicationDeliveryJournalPage,
  mockCommunicationDeliveryLifecyclePage,
  mockCommunicationDeliveryLifecyclePage2,
  mockCommunicationReconnectResponse,
  mockCommunicationPlatforms,
  mockCreatedCommunicationConnection,
  mockUpdatedCommunicationConnection,
} from "../../fixtures/communication-connections";

export class CommunicationConnectionDataSupport {
  constructor(private page: Page) {}

  async interceptChannelsRequests({ agentId }: { agentId: string }) {
    await this.page.route("**/api/v1/organizations/*/communication-platforms", async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockCommunicationPlatforms),
      });
    });

    await this.page.route(`**/api/v1/organizations/*/agents/${agentId}/connections`, async (route) => {
      if (route.request().method() === "POST") {
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify(mockCreatedCommunicationConnection),
        });
        return;
      }
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([mockCommunicationConnection]),
      });
    });

    await this.page.route(`**/api/v1/organizations/*/agents/${agentId}/connections/*`, async (route) => {
      const url = new URL(route.request().url());
      if (route.request().method() === "GET" && url.pathname.includes("/directory/")) {
        const kind = url.pathname.split("/directory/")[1];
        const entries = {
          guilds: [{ id: "guild-one", label: "Community", detail: null }],
          channels: [{ id: "channel-one", label: "#general", detail: null }],
          users: [{ id: "user-one", label: "Aria", detail: null }],
          roles: [{ id: "role-one", label: "@Maintainer", detail: null }],
        }[kind] ?? [];
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(entries) });
        return;
      }
      if (route.request().method() !== "GET" && route.request().method() !== "PATCH") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(
          route.request().method() === "PATCH"
            ? mockUpdatedCommunicationConnection
            : { ...mockCommunicationConnection, id: COMMUNICATION_CONNECTION_ID },
        ),
      });
    });

    await this.page.route(`**/api/v1/organizations/*/agents/${agentId}/connections/*/summary`, async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockCommunicationConnectionSummary),
      });
    });

    await this.page.route(`**/api/v1/organizations/*/agents/${agentId}/connections/*/journal?*`, async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      const url = new URL(route.request().url());
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(
          url.searchParams.get("kind") === "connection"
            ? mockCommunicationConnectionJournalPage
            : url.searchParams.has("delivery_id")
              ? url.searchParams.get("page") === "2"
                ? mockCommunicationDeliveryLifecyclePage2
                : mockCommunicationDeliveryLifecyclePage
              : mockCommunicationDeliveryJournalPage,
        ),
      });
    });

    await this.page.route(new RegExp(`/agents/${agentId}/connections/[^/]+/directory/[^/?]+`), async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      const kind = new URL(route.request().url()).pathname.split("/directory/")[1];
      const entries = {
        guilds: [{ id: "guild-one", label: "Community", detail: null }],
        channels: [{ id: "channel-one", label: "#general", detail: null }],
        users: [{ id: "user-one", label: "Aria", detail: null }],
        roles: [{ id: "role-one", label: "@Maintainer", detail: null }],
      }[kind] ?? [];
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(entries) });
    });

    await this.page.route(`**/api/v1/organizations/*/agents/${agentId}/connections/*/reconnect`, async (route) => {
      if (route.request().method() !== "POST") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify(mockCommunicationReconnectResponse),
      });
    });
  }
}
