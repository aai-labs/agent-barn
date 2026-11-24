import type { Page } from "@playwright/test";

export type OpenRouterConnectionBody = {
  has_api_key: boolean;
  api_key_last4: string | null;
  updated_at: string | null;
  updated_by: string | null;
  env_key_configured: boolean;
  env_key_last4: string | null;
};

export type ProviderAccessBody = {
  organization_access: "all" | "none" | "all_except" | "only";
  organization_count: number;
};

export type LlmProviderConnectionBody = OpenRouterConnectionBody &
  ProviderAccessBody & {
  slug: string;
  name: string;
  provider_type: string;
  base_url: string | null;
};

type AddBody = {
  provider_type: string;
  api_key: string;
  slug?: string;
  name?: string;
  base_url?: string;
  organization_access?: ProviderAccessBody["organization_access"];
  organization_ids?: string[];
};
type KeyBody = { api_key: string; base_url?: string };

export type ModelPricesBody = {
  input_cost_per_token: string;
  output_cost_per_token: string;
  cache_read_input_token_cost: string;
  cache_creation_input_token_cost: string;
};

export type ModelBody = ModelPricesBody & {
  model_id: string;
  price_source: "litellm" | "manual";
  litellm_price_key: string | null;
};

export type CatalogueEntryBody = {
  model_id: string;
  stored: boolean;
  litellm_price_key: string | null;
  input_cost_per_token: string | null;
  output_cost_per_token: string | null;
  cache_read_input_token_cost: string | null;
  cache_creation_input_token_cost: string | null;
  prices_differ: boolean;
};

export type ModelsSaveBody = {
  models: { model_id: string; price: string | ModelPricesBody; runs_model?: string }[];
};

const HAIKU_PRICES: ModelPricesBody = {
  input_cost_per_token: "0.000001000000000000",
  output_cost_per_token: "0.000005000000000000",
  cache_read_input_token_cost: "0.000000100000000000",
  cache_creation_input_token_cost: "0.000001250000000000",
};

const OPUS_LISTED_PRICES: ModelPricesBody = {
  input_cost_per_token: "0.000015000000000000",
  output_cost_per_token: "0.000075000000000000",
  cache_read_input_token_cost: "0.0000015",
  cache_creation_input_token_cost: "0.000018750000000000",
};

const OPUS_STORED_PRICES: ModelPricesBody = {
  input_cost_per_token: "0.000012000000000000",
  output_cost_per_token: "0.000060000000000000",
  cache_read_input_token_cost: "0.000001500000000000",
  cache_creation_input_token_cost: "0.000015000000000000",
};

const SONNET_PRICES: ModelPricesBody = {
  input_cost_per_token: "0.000003000000000000",
  output_cost_per_token: "0.000015000000000000",
  cache_read_input_token_cost: "0.000000300000000000",
  cache_creation_input_token_cost: "0.000003750000000000",
};

const NO_PRICES = {
  litellm_price_key: null,
  input_cost_per_token: null,
  output_cost_per_token: null,
  cache_read_input_token_cost: null,
  cache_creation_input_token_cost: null,
};

export const ANTHROPIC_STORED_MODELS: ModelBody[] = [
  { model_id: "claude-opus-4-1", ...OPUS_STORED_PRICES, price_source: "litellm", litellm_price_key: "claude-opus-4-1" },
  { model_id: "claude-sonnet-4-5", ...SONNET_PRICES, price_source: "litellm", litellm_price_key: "claude-sonnet-4-5" },
];

export const DROPPED_MODEL: ModelBody = {
  model_id: "claude-3-opus-20240229",
  ...OPUS_LISTED_PRICES,
  price_source: "litellm",
  litellm_price_key: "claude-3-opus-20240229",
};

export const ANTHROPIC_CATALOGUE: CatalogueEntryBody[] = [
  {
    model_id: "claude-haiku-4-5",
    stored: false,
    litellm_price_key: "claude-haiku-4-5",
    ...HAIKU_PRICES,
    prices_differ: false,
  },
  {
    model_id: "claude-opus-4-1",
    stored: true,
    litellm_price_key: "claude-opus-4-1",
    ...OPUS_LISTED_PRICES,
    prices_differ: true,
  },
  {
    model_id: "claude-sonnet-4-5",
    stored: true,
    litellm_price_key: "claude-sonnet-4-5",
    ...SONNET_PRICES,
    prices_differ: false,
  },
  { model_id: "claude-unpriced-preview", stored: false, ...NO_PRICES, prices_differ: false },
];

export function pricedCatalogue(
  count: number,
  stored: number,
): { catalogue: CatalogueEntryBody[]; models: ModelBody[] } {
  const ids = Array.from({ length: count }, (_, index) => `model-${String(index).padStart(2, "0")}`);
  return {
    catalogue: ids.map((model_id, index) => ({
      model_id,
      stored: index < stored,
      litellm_price_key: model_id,
      ...HAIKU_PRICES,
      prices_differ: false,
    })),
    models: ids
      .slice(0, stored)
      .map((model_id) => ({ model_id, ...HAIKU_PRICES, price_source: "litellm", litellm_price_key: model_id })),
  };
}

const AZURE_GPT4O_PRICES: ModelPricesBody = {
  input_cost_per_token: "0.000002500000000000",
  output_cost_per_token: "0.000010000000000000",
  cache_read_input_token_cost: "0.000001250000000000",
  cache_creation_input_token_cost: "0.000002500000000000",
};

const AZURE_GPT4O_OLD_PRICES: ModelPricesBody = {
  input_cost_per_token: "0.000002000000000000",
  output_cost_per_token: "0.000008000000000000",
  cache_read_input_token_cost: "0.000001250000000000",
  cache_creation_input_token_cost: "0.000002000000000000",
};

export const AZURE_CATALOGUE: CatalogueEntryBody[] = [
  {
    model_id: "eu/gpt-4o",
    stored: false,
    litellm_price_key: "azure/eu/gpt-4o",
    input_cost_per_token: "0.000002750000000000",
    output_cost_per_token: "0.000011000000000000",
    cache_read_input_token_cost: "0.000001375000000000",
    cache_creation_input_token_cost: "0.000002750000000000",
    prices_differ: false,
  },
  {
    model_id: "gpt-4o",
    stored: true,
    litellm_price_key: "azure/gpt-4o",
    ...AZURE_GPT4O_PRICES,
    prices_differ: true,
  },
  {
    model_id: "gpt-4o-mini",
    stored: false,
    litellm_price_key: "azure/gpt-4o-mini",
    input_cost_per_token: "0.000000150000000000",
    output_cost_per_token: "0.000000600000000000",
    cache_read_input_token_cost: "0.000000075000000000",
    cache_creation_input_token_cost: "0.000000150000000000",
    prices_differ: false,
  },
];

export const AZURE_DEPLOYMENTS: ModelBody[] = [
  {
    model_id: "lab-router",
    input_cost_per_token: "0.000001000000000000",
    output_cost_per_token: "0.000002000000000000",
    cache_read_input_token_cost: "0.000000000000000000",
    cache_creation_input_token_cost: "0.000000000000000000",
    price_source: "manual",
    litellm_price_key: null,
  },
  { model_id: "prod-gpt4o", ...AZURE_GPT4O_OLD_PRICES, price_source: "litellm", litellm_price_key: "azure/gpt-4o" },
];

export const CUSTOM_CATALOGUE: CatalogueEntryBody[] = [
  { model_id: "llama-3", stored: false, ...NO_PRICES, prices_differ: false },
  { model_id: "mistral-7b", stored: true, ...NO_PRICES, prices_differ: false },
];

export const CUSTOM_MODELS: ModelBody[] = [
  {
    model_id: "mistral-7b",
    input_cost_per_token: "0.000000200000000000",
    output_cost_per_token: "0.000000400000000000",
    cache_read_input_token_cost: "0.000000000000000000",
    cache_creation_input_token_cost: "0.000000000000000000",
    price_source: "manual",
    litellm_price_key: null,
  },
];

export const SAVED_KEY: OpenRouterConnectionBody = {
  has_api_key: true,
  api_key_last4: "a1b2",
  updated_at: "2026-11-16T09:30:00Z",
  updated_by: "Platform Person",
  env_key_configured: false,
  env_key_last4: null,
};

export const ENVIRONMENT_KEY_ONLY: OpenRouterConnectionBody = {
  has_api_key: false,
  api_key_last4: null,
  updated_at: null,
  updated_by: null,
  env_key_configured: true,
  env_key_last4: "9z8y",
};

export const SAVED_AND_ENVIRONMENT_KEYS: OpenRouterConnectionBody = {
  ...SAVED_KEY,
  env_key_configured: true,
  env_key_last4: "9z8y",
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
  env_key_last4: null,
  organization_access: "all",
  organization_count: 0,
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
  env_key_last4: null,
  organization_access: "all",
  organization_count: 0,
};

export const CUSTOM_CONNECTION: LlmProviderConnectionBody = {
  slug: "lab",
  name: "Aardvark lab",
  provider_type: "custom",
  base_url: "https://lab.example.com/v1",
  has_api_key: true,
  api_key_last4: "m1n2",
  updated_at: "2026-11-16T09:30:00Z",
  updated_by: "Platform Person",
  env_key_configured: false,
  env_key_last4: null,
  organization_access: "all",
  organization_count: 0,
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
      connection?: OpenRouterConnectionBody & Partial<ProviderAccessBody>;
      connections?: LlmProviderConnectionBody[];
      listStatus?: number;
      saveStatus?: number;
      saveDetail?: string;
      /** How long a key save takes to answer, as a real provider check does. */
      saveDelayMs?: number;
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
        organization_access: "all",
        organization_count: 0,
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
          env_key_last4: null,
          organization_access: body.organization_access ?? "all",
          organization_count: body.organization_ids?.length ?? 0,
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
      if (options.saveDelayMs) await new Promise((resolve) => setTimeout(resolve, options.saveDelayMs));
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

  async interceptModels(
    options: {
      catalogue?: CatalogueEntryBody[];
      models?: ModelBody[];
      catalogueStatus?: number;
      catalogueDetail?: string;
      saveStatus?: number;
      saveDetail?: string;
    } = {},
  ) {
    let catalogue = options.catalogue ?? ANTHROPIC_CATALOGUE;
    let models = options.models ?? ANTHROPIC_STORED_MODELS;
    let catalogueStatus = options.catalogueStatus ?? 200;
    const catalogueDetail = options.catalogueDetail ?? "The provider could not be reached to list its models.";
    const saveStatus = options.saveStatus ?? 200;
    const saveDetail = options.saveDetail ?? "The model proxy could not be updated. Your models were not changed.";
    const saves: { slug: string; body: ModelsSaveBody }[] = [];
    const catalogueReads: string[] = [];
    const json = (status: number, body: unknown) => ({
      status,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
    const slugOf = (url: string) => decodeURIComponent(new URL(url).pathname.slice(BASE.length + 1).split("/")[0]);

    await this.page.route(`**${BASE}/*/model-catalogue`, async (route) => {
      catalogueReads.push(slugOf(route.request().url()));
      if (catalogueStatus >= 400) return route.fulfill(json(catalogueStatus, { detail: catalogueDetail }));
      return route.fulfill(json(200, catalogue));
    });

    await this.page.route(`**${BASE}/*/models`, async (route) => {
      if (route.request().method() !== "PUT") return route.fulfill(json(200, models));
      const body = route.request().postDataJSON() as ModelsSaveBody;
      saves.push({ slug: slugOf(route.request().url()), body });
      if (saveStatus >= 400) return route.fulfill(json(saveStatus, { detail: saveDetail }));
      models = body.models
        .map(({ model_id, price, runs_model }): ModelBody => {
          const stored = models.find((model) => model.model_id === model_id);
          if (price === "stored" && stored) return stored;
          if (typeof price === "object") return { model_id, ...price, price_source: "manual", litellm_price_key: null };
          const entry = catalogue.find((item) => item.model_id === (runs_model ?? model_id));
          return {
            model_id,
            input_cost_per_token: entry?.input_cost_per_token ?? "",
            output_cost_per_token: entry?.output_cost_per_token ?? "",
            cache_read_input_token_cost: entry?.cache_read_input_token_cost ?? "",
            cache_creation_input_token_cost: entry?.cache_creation_input_token_cost ?? "",
            price_source: "litellm",
            litellm_price_key: entry?.litellm_price_key ?? null,
          };
        })
        .sort((left, right) => left.model_id.localeCompare(right.model_id));
      catalogue = catalogue.map((entry) => ({
        ...entry,
        stored: models.some((model) => model.model_id === entry.model_id),
      }));
      return route.fulfill(json(200, models));
    });

    return {
      saves,
      catalogueReads,
      recover: () => {
        catalogueStatus = 200;
      },
      replace: (next: { catalogue: CatalogueEntryBody[]; models: ModelBody[] }) => {
        catalogue = next.catalogue;
        models = next.models;
      },
    };
  }
}
