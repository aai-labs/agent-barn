import { ApiClient } from "./api-client";
import type { ApiClientConfig } from "../types";

export const defaultConfig = {
  timeout: 30000,
  headers: {},
  transformKeys: true,
  retryAttempts: 3,
  retryDelay: 1000,
};

export const createApiClient = (config: ApiClientConfig): ApiClient => {
  return new ApiClient({ ...defaultConfig, ...config });
};
