import axios from "axios";
import { camelizeKeys } from "humps";
import { ApiError } from "../error/errors";
import { AxiosInstance, InternalAxiosRequestConfig } from "axios";
import { AuthConfig, AuthTokens } from "../types";

type AuthAwareRequestConfig = InternalAxiosRequestConfig & {
  skipAuth?: boolean;
  _retried?: boolean;
};

export class AuthInterceptor {
  private refreshPromise: Promise<AuthTokens> | null = null;
  private config: Required<AuthConfig>;
  private refreshAxios: AxiosInstance;

  constructor(
    private axiosInstance: AxiosInstance,
    authConfig: AuthConfig,
  ) {
    this.config = {
      refreshBufferMs: 60000,
      onSessionExpired: () => {},
      ...authConfig,
    };

    this.refreshAxios = axios.create({
      baseURL: this.axiosInstance.defaults.baseURL,
      timeout: this.axiosInstance.defaults.timeout,
      withCredentials: this.axiosInstance.defaults.withCredentials,
    });

    this.setupInterceptors();
  }

  private setupInterceptors(): void {
    this.axiosInstance.interceptors.request.use(
      async (config) => await this.attachAuthToken(config),
      (error) => Promise.reject(error),
    );

    this.axiosInstance.interceptors.response.use(
      (response) => response,
      async (error) => await this.handleAuthError(error),
    );
  }

  private async attachAuthToken(
    config: AuthAwareRequestConfig,
  ): Promise<AuthAwareRequestConfig> {
    if (config.url === this.config.refreshUrl || config.skipAuth) {
      return config;
    }

    try {
      const tokens = await this.getValidTokens();
      if (tokens?.accessToken) {
        config.headers.Authorization = `Bearer ${tokens.accessToken}`;
      }
    } catch (error) {
      console.warn("Failed to attach auth token:", error);
    }

    return config;
  }

  private async handleAuthError(error: ApiError): Promise<any> {
    const originalRequest = error.internalError?.config as
      | AuthAwareRequestConfig
      | undefined;

    if (
      error.status === 401 &&
      originalRequest &&
      !originalRequest.skipAuth &&
      !originalRequest._retried
    ) {
      originalRequest._retried = true;
      try {
        const tokens = await this.refreshTokens();
        if (tokens) {
          originalRequest.headers.Authorization = `Bearer ${tokens.accessToken}`;
          return this.axiosInstance(originalRequest);
        }
      } catch (_) {
        this.config.onSessionExpired?.();
        throw ApiError.unauthorizedError("Token refresh failed.");
      }
    }

    throw error instanceof ApiError
      ? error
      : new ApiError("Request failed", 500);
  }

  private async getValidTokens(): Promise<AuthTokens | null> {
    const tokens = this.config.getTokens();
    if (!tokens) {
      return await this.refreshTokens();
    }

    if (this.isTokenNearExpiry(tokens)) {
      return await this.refreshTokens();
    }

    return tokens;
  }

  private isTokenNearExpiry(tokens: AuthTokens): boolean {
    if (!tokens.expiresAt) return false;

    const now = Date.now();
    const expiryTime = tokens.expiresAt * 1000;
    const bufferTime = this.config.refreshBufferMs;

    return now >= expiryTime - bufferTime;
  }

  private async refreshTokens(): Promise<AuthTokens | null> {
    if (this.refreshPromise) {
      try {
        return await this.refreshPromise;
      } catch {
        return null;
      }
    }

    this.refreshPromise = this.performTokenRefresh();

    try {
      return await this.refreshPromise;
    } catch {
      return null;
    } finally {
      this.refreshPromise = null;
    }
  }

  private async performTokenRefresh(): Promise<AuthTokens> {
    try {
      const currentTokens = this.config.getTokens();

      const response = currentTokens?.refreshToken
        ? await this.refreshAxios.post(this.config.refreshUrl, {
            refresh_token: currentTokens.refreshToken,
          })
        : await this.refreshAxios.post(this.config.refreshUrl);

      const data = camelizeKeys(response.data);
      const newTokens: AuthTokens = {
        accessToken: data.accessToken,
        refreshToken: data.refreshToken,
        expiresAt: data.expiresAt,
      };

      this.config.setTokens(newTokens);
      return newTokens;
    } catch (_) {
      this.config.onSessionExpired?.();
      throw new Error("Token refresh failed");
    }
  }

  public clearAuth(): void {
    this.config.clearTokens();
  }

  public async getTokens(): Promise<AuthTokens | null> {
    return this.getValidTokens();
  }
}
