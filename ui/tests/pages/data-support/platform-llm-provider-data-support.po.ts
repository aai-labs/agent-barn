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
type KeyBody = { api_key: string; base_url?: string };

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

const BASE = "/api/v1/platform/settings/llm-providers";

function trimmedBaseUrl(value: string): string {
  return value.trim().replace(/\/+$/, "");
}

export class PlatformLlmProviderDataSupport {
  constructor(private page: Page) {}

  async intercept(
    options: {
      connection?: OpenRouterConnectionBody;
      connections?: LlmProviderConnectionBody[];
      listStatus?: number;
      saveStatus?: number;
      saveDetail?: string;
      addStatus?: number;
      addDetail?: string;
      deleteStatus?: number;
      deleteDetail?: string;
    } = {},
  ) {
    const rows: LlmProviderConnectionBody[] = [
      {
        slug: "openrouter",
        name: "OpenRouter",
        provider_type: "openrouter",
        base_url: null,
        ...(options.connection ?? SAVED_KEY),
      },
      ...(options.connections ?? []),
    ];
    let listStatus = options.listStatus ?? 200;
    let saveStatus = options.saveStatus ?? 200;
    let addStatus = options.addStatus ?? 201;
    let deleteStatus = options.deleteStatus ?? 204;
    const saveDetail = options.saveDetail ?? "OpenRouter did not accept this key. Your key was not changed.";
    const addDetail = options.addDetail ?? "The provider did not accept this key. Nothing was saved.";
    const deleteDetail = options.deleteDetail ?? "That connection does not exist.";
    const writes: { slug: string; body: KeyBody }[] = [];
    const adds: AddBody[] = [];
    const deletes: string[] = [];
    const reads: string[] = [];
    const refuse = (status: number, detail: string) => ({
      status,
      contentType: "application/json",
      body: JSON.stringify({ detail }),
    });
    const slugOf = (url: string) => decodeURIComponent(new URL(url).pathname.slice(BASE.length + 1).split("/")[0]);

    await this.page.route(`**${BASE}`, async (route) => {
      if (route.request().method() === "POST") {
        const body = route.request().postDataJSON() as AddBody;
        adds.push(body);
        if (addStatus >= 400) return route.fulfill(refuse(addStatus, addDetail));
        const added: LlmProviderConnectionBody = {
          slug: body.slug ?? body.provider_type,
          name: body.name?.trim() ?? KNOWN_PROVIDER_NAMES[body.provider_type],
          provider_type: body.provider_type,
          base_url: body.base_url === undefined ? null : trimmedBaseUrl(body.base_url),
          has_api_key: true,
          api_key_last4: body.api_key.trim().slice(-4),
          updated_at: "2026-11-16T10:00:00Z",
          updated_by: "Platform Person",
          env_key_configured: false,
        };
        rows.push(added);
        return route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(added) });
      }
      reads.push("list");
      if (listStatus >= 400) {
        return route.fulfill(refuse(listStatus, "LLM provider settings are unavailable. Try again."));
      }
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(rows) });
    });

    await this.page.route(`**${BASE}/*/key`, async (route) => {
      const slug = slugOf(route.request().url());
      const body = route.request().postDataJSON() as KeyBody;
      writes.push({ slug, body });
      if (saveStatus >= 400) return route.fulfill(refuse(saveStatus, saveDetail));
      const index = rows.findIndex((row) => row.slug === slug);
      rows[index] = {
        ...rows[index],
        base_url: body.base_url === undefined ? rows[index].base_url : trimmedBaseUrl(body.base_url),
        has_api_key: true,
        api_key_last4: body.api_key.trim().slice(-4),
        updated_at: "2026-11-16T10:00:00Z",
        updated_by: "Platform Person",
      };
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(rows[index]) });
    });

    await this.page.route(`**${BASE}/*`, async (route) => {
      if (route.request().method() !== "DELETE") return route.fallback();
      const slug = slugOf(route.request().url());
      deletes.push(slug);
      if (deleteStatus >= 400) return route.fulfill(refuse(deleteStatus, deleteDetail));
      rows.splice(
        rows.findIndex((row) => row.slug === slug),
        1,
      );
      return route.fulfill({ status: 204 });
    });

    return {
      writes,
      adds,
      deletes,
      reads,
      recover: () => {
        listStatus = 200;
        saveStatus = 200;
        addStatus = 201;
        deleteStatus = 204;
      },
    };
  }
}
