import type { Page } from "@playwright/test";

export type OpenRouterConnectionBody = {
  has_api_key: boolean;
  api_key_last4: string | null;
  updated_at: string | null;
  updated_by: string | null;
  env_key_configured: boolean;
};

export const SAVED_KEY: OpenRouterConnectionBody = {
  has_api_key: true,
  api_key_last4: "a1b2",
  updated_at: "2026-11-16T09:30:00Z",
  updated_by: "Platform Person",
  env_key_configured: false,
};

export class PlatformLlmProviderDataSupport {
  constructor(private page: Page) {}

  async intercept(
    options: {
      connection?: OpenRouterConnectionBody;
      readStatus?: number;
      saveStatus?: number;
      saveDetail?: string;
    } = {},
  ) {
    let connection = options.connection ?? SAVED_KEY;
    let readStatus = options.readStatus ?? 200;
    let saveStatus = options.saveStatus ?? 200;
    const saveDetail = options.saveDetail ?? "OpenRouter did not accept this key. Your key was not changed.";
    const writes: unknown[] = [];
    const reads: string[] = [];
    await this.page.route("**/api/v1/platform/settings/llm-providers/openrouter", async (route) => {
      const writing = route.request().method() === "PUT";
      if (!writing) {
        reads.push("openrouter");
        if (readStatus >= 400) {
          return route.fulfill({
            status: readStatus,
            contentType: "application/json",
            body: JSON.stringify({ detail: "LLM provider settings are unavailable. Try again." }),
          });
        }
        return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(connection) });
      }
      const body = route.request().postDataJSON() as { api_key: string };
      writes.push(body);
      if (saveStatus >= 400) {
        return route.fulfill({
          status: saveStatus,
          contentType: "application/json",
          body: JSON.stringify({ detail: saveDetail }),
        });
      }
      connection = {
        ...connection,
        has_api_key: true,
        api_key_last4: body.api_key.trim().slice(-4),
        updated_at: "2026-11-16T10:00:00Z",
        updated_by: "Platform Person",
      };
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(connection) });
    });
    return {
      writes,
      reads,
      recover: () => {
        readStatus = 200;
        saveStatus = 200;
      },
    };
  }
}
