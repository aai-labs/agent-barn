import { Page } from "@playwright/test";

import UserContext from "../../fixtures/user-context.json";

export class UserDataSupport {
  constructor(private page: Page) {}

  async interceptGetUserContextRequest({
    userContext,
    unauthorized = false,
  }: {
    userContext?: unknown;
    unauthorized?: boolean;
  } = {}) {
    await this.page.route("/api/v1/auth/me", async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }

      if (unauthorized) {
        await route.fulfill({
          status: 401,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Unauthorized" }),
        });
        return;
      }

      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(userContext ?? UserContext),
      });
    });
  }
}
