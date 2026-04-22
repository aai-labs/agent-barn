import type { AxiosHeaders, AxiosRequestConfig } from "axios";
import type { ZodType } from "zod";

export interface ApiClientConfig {
  baseURL: string;
  timeout?: number;
  headers?: Record<string, string>;
  transformKeys?: boolean;
  retryAttempts?: number;
  retryDelay?: number;
}

export interface ApiResult<T = any> {
  data: T;
  status: number;
  message?: string;
  headers?: AxiosHeaders | Record<string, any>;
}

export interface RequestOptions<T = any>
  extends Omit<AxiosRequestConfig, "data"> {
  data?: any;
  schema?: ZodType<T, any, any>;
  signal?: AbortSignal;
  skipAuth?: boolean;
}

export interface AuthTokens {
  accessToken: string;
  refreshToken?: string;
  expiresAt?: number;
}

export interface AuthConfig {
  refreshUrl: string;
  getTokens: () => AuthTokens | null;
  setTokens: (tokens: AuthTokens) => void;
  clearTokens: () => void;
  onSessionExpired?: () => void;
  refreshBufferMs?: number;
}
