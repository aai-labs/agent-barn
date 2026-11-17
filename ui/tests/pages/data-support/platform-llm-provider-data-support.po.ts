import type { Page } from "@playwright/test";

export type OpenRouterConnectionBody = {
  has_api_key: boolean;
  api_key_last4: string | null;
  updated_at: string | null;
  updated_by: string | null;
  env_key_configured: boolean;
};

export type LlmProviderConnectionBody = OpenRouterConnectionBody & {
  slug: string;
  name: string;
  provider_type: string;
  base_url: string | null;
};

type AddBody = { provider_type: string; api_key: string; slug?: string; name?: string; base_url?: string };

export const SAVED_KEY: OpenRouterConnectionBody = {
  has_api_key: true,
  api_key_last4: "a1b2",
  updated_at: "2026-11-16T09:30:00Z",
  updated_by: "Platform Person",
  env_key_configured: false,
};

export const ANTHROPIC_CONNECTION: LlmProviderConnectionBody = {
  slug: "anthropic",
  name: "Anthropic",
  provider_type: "anthropic",
  base_url: null,
  has_api_key: true,
  api_key_last4: "c3d4",
  updated_at: "2026-11-16T09:30:00Z",
  updated_by: "Platform Person",
  env_key_configured: false,
};

export const AZURE_CONNECTION: LlmProviderConnectionBody = {
  slug: "azure-eu",
  name: "Azure Europe",
  provider_type: "azure",
  base_url: "https://contoso.openai.azure.com",
  has_api_key: true,
  api_key_last4: "e5f6",
  updated_at: "2026-11-16T09:30:00Z",
  updated_by: "Platform Person",
  env_key_configured: false,
};

const KNOWN_PROVIDER_NAMES: Record<string, string> = {
  anthropic: "Anthropic",
  openai: "OpenAI",
  gemini: "Gemini",
  xai: "xAI",
  deepseek: "DeepSeek",
  fireworks: "Fireworks",
  novita: "Novita",
};

export class PlatformLlmProviderDataSupport {
  constructor(private page: Page) {}

  async intercept(
    options: {
      connection?: OpenRouterConnectionBody;
      connections?: LlmProviderConnectionBody[];
      readStatus?: number;
      listStatus?: number;
      saveStatus?: number;
      saveDetail?: string;
      addStatus?: number;
      addDetail?: string;
    } = {},
  ) {
    let connection = options.connection ?? SAVED_KEY;
    const connections = [...(options.connections ?? [])];
    let readStatus = options.readStatus ?? 200;
    let listStatus = options.listStatus ?? 200;
    let saveStatus = options.saveStatus ?? 200;
    let addStatus = options.addStatus ?? 201;
    const saveDetail = options.saveDetail ?? "OpenRouter did not accept this key. Your key was not changed.";
    const addDetail = options.addDetail ?? "The provider did not accept this key. Nothing was saved.";
    const writes: unknown[] = [];
    const adds: AddBody[] = [];
    const reads: string[] = [];
    const unavailable = { detail: "LLM provider settings are unavailable. Try again." };
    await this.page.route("**/api/v1/platform/settings/llm-providers", async (route) => {
      if (route.request().method() === "POST") {
        const body = route.request().postDataJSON() as AddBody;
        adds.push(body);
        if (addStatus >= 400) {
          return route.fulfill({
            status: addStatus,
            contentType: "application/json",
            body: JSON.stringify({ detail: addDetail }),
          });
        }
        const added: LlmProviderConnectionBody = {
          slug: body.slug ?? body.provider_type,
          name: body.name?.trim() ?? KNOWN_PROVIDER_NAMES[body.provider_type],
          provider_type: body.provider_type,
          base_url: body.base_url?.trim().replace(/\/+$/, "") ?? null,
          has_api_key: true,
          api_key_last4: body.api_key.trim().slice(-4),
          updated_at: "2026-11-16T10:00:00Z",
          updated_by: "Platform Person",
          env_key_configured: false,
        };
        connections.push(added);
        return route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(added) });
      }
      reads.push("list");
      if (listStatus >= 400) {
        return route.fulfill({ status: listStatus, contentType: "application/json", body: JSON.stringify(unavailable) });
      }
      const openrouter: LlmProviderConnectionBody = {
        slug: "openrouter",
        name: "OpenRouter",
        provider_type: "openrouter",
        base_url: null,
        ...connection,
      };
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([openrouter, ...connections]),
      });
    });
    await this.page.route("**/api/v1/platform/settings/llm-providers/openrouter", async (route) => {
      const writing = route.request().method() === "PUT";
      if (!writing) {
        reads.push("openrouter");
        if (readStatus >= 400) {
          return route.fulfill({
            status: readStatus,
            contentType: "application/json",
            body: JSON.stringify(unavailable),
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
      adds,
      reads,
      recover: () => {
        readStatus = 200;
        listStatus = 200;
        saveStatus = 200;
        addStatus = 201;
      },
    };
  }
}
