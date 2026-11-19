import type { Page, Route } from "@playwright/test";

function json(route: Route, status: number, body: unknown) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

export class DecisionDataSupport {
  constructor(private page: Page) {}

  async interceptPlatformSettings({ model = "jev" } = {}) {
    const writes: unknown[] = [];
    let current = model;
    await this.page.route("**/api/v1/platform/settings/decisions/models", (route) =>
      json(route, 200, [
        { value: "jev", label: "jev (typesafe/jev-1.14)" },
        { value: "openai", label: "openai (openai/gpt-6-luna-decisions)" },
      ]),
    );
    await this.page.route("**/api/v1/platform/settings/decisions", async (route) => {
      if (route.request().method() === "PUT") {
        const payload = route.request().postDataJSON();
        writes.push(payload);
        current = payload.model;
      }
      return json(route, 200, { model: current, updated_at: null });
    });
    return { writes };
  }
}
