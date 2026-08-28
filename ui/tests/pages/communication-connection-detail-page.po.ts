import { Locator, Page, Request } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";

export class CommunicationConnectionDetailPage {
  constructor(private page: Page) {}

  async goto(agentId: string, connectionId: string) {
    await this.page.goto(`/dashboard/${TEST_ORG_ID}/agents/${agentId}/connections/${connectionId}`);
  }

  providerErrorAlert(): Locator {
    return this.page.getByRole("alert").filter({ hasText: "Latest provider error" });
  }

  providerErrorMessage(): Locator {
    return this.providerErrorAlert().locator("p");
  }

  summaryMetric(label: string): Locator {
    return this.page.getByText(label, { exact: true });
  }

  activityPanel(kind: "delivery" | "connection"): Locator {
    return this.page.locator(`[data-activity-kind="${kind}"]`);
  }

  connectionHealthSummary(): Locator {
    return this.page.getByText(/Median connect time/);
  }

  recentFailureCard(): Locator {
    return this.page.locator("[data-failure-card]").first();
  }

  failureDetailsToggle(): Locator {
    return this.recentFailureCard().getByRole("button", { name: /Show details|Hide details/ });
  }

  deliveryEventCount(count: number): Locator {
    return this.activityPanel("delivery").getByText(`${count} ${count === 1 ? "event" : "events"}`, { exact: true });
  }

  deliveryTransitionRow(stage: string | RegExp): Locator {
    return this.activityPanel("delivery").getByRole("button", { name: stage });
  }

  deliveryTiming(): Locator {
    return this.activityPanel("delivery").getByText("Delivery timing", { exact: true });
  }

  waitBeforeAttempt(): Locator {
    return this.activityPanel("delivery").getByText("Wait before attempt", { exact: true });
  }

  copyErrorButton(stage: string): Locator {
    return this.activityPanel("delivery").getByRole("button", { name: `Copy error for ${stage}`, exact: true });
  }

  failedOnlyCheckbox(): Locator {
    return this.activityPanel("delivery").getByLabel("Failed only", { exact: true });
  }

  deliveryTimelineButton(): Locator {
    return this.activityPanel("delivery").getByRole("button", { name: "View delivery timeline", exact: true });
  }

  deliveryTimeline(): Locator {
    return this.activityPanel("delivery").getByRole("list");
  }

  timelineStage(stage: string): Locator {
    return this.deliveryTimeline().getByText(stage, { exact: true });
  }

  reconnectButton(): Locator {
    return this.page.getByRole("button", { name: "Reconnect", exact: true }).first();
  }

  reconnectDialog(): Locator {
    return this.page.getByRole("dialog", { name: "Reconnect this connection?" });
  }

  confirmReconnectButton(): Locator {
    return this.reconnectDialog().getByRole("button", { name: "Reconnect", exact: true });
  }

  waitForJournalRequest(kind: "delivery" | "connection"): Promise<Request> {
    return this.page.waitForRequest(
      (request) => request.url().includes("/journal?") && request.url().includes(`kind=${kind}`),
    );
  }

  waitForFailedOnlyRequest(): Promise<Request> {
    return this.page.waitForRequest((request) => request.url().includes("failed_only=true"));
  }

  waitForDeliveryLifecycleRequest(deliveryId: string): Promise<Request> {
    return this.page.waitForRequest(
      (request) => request.url().includes(`delivery_id=${deliveryId}`) && request.url().includes("order=asc"),
    );
  }

  waitForDeliveryLifecyclePageRequest(deliveryId: string, page: number): Promise<Request> {
    return this.page.waitForRequest(
      (request) => request.url().includes(`delivery_id=${deliveryId}`)
        && request.url().includes("order=asc")
        && request.url().includes(`page=${page}`),
    );
  }

  waitForReconnectRequest(): Promise<Request> {
    return this.page.waitForRequest(
      (request) => request.method() === "POST" && request.url().endsWith("/reconnect"),
    );
  }

  async readClipboard(): Promise<string> {
    return this.page.evaluate(() => navigator.clipboard.readText());
  }

  startJournalRequestCapture(): { urls: string[]; stop: () => void } {
    const urls: string[] = [];
    const listener = (request: Request) => {
      if (request.url().includes("/journal?")) urls.push(request.url());
    };
    this.page.on("request", listener);
    return {
      urls,
      stop: () => this.page.off("request", listener),
    };
  }
}
