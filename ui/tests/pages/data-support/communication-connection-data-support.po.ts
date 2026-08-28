import { Page } from "@playwright/test";

import {
  COMMUNICATION_CONNECTION_ID,
  mockCommunicationConnection,
  mockCommunicationConnectionSummary,
  mockCommunicationDeliveryJournalPage,
  mockCommunicationDeliveryLifecyclePage,
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
          url.searchParams.has("delivery_id")
            ? mockCommunicationDeliveryLifecyclePage
            : mockCommunicationDeliveryJournalPage,
        ),
      });
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
