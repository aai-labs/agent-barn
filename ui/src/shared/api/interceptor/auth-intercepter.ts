import axios from "axios";
import { camelizeKeys } from "humps";
import { ApiError } from "../error/errors";
import { handleError } from "../error/error-handler";
import { isServerUnavailable } from "../error/server-unavailable";
import { AxiosInstance, InternalAxiosRequestConfig } from "axios";
import { AuthConfig, AuthTokens } from "../types";

type AuthAwareRequestConfig = InternalAxiosRequestConfig & {
  skipAuth?: boolean;
  _retried?: boolean;
};

/**
 * The server answered the refresh and refused it: the token is missing, expired or
 * revoked, or its user is gone. Only this ends the session. When the API is down,
 * unreachable, slow or failing (no response, 5xx, 408, 429) the refresh cookie may still
 * be good, so the session stays and the next request tries again.
 */
function isRefreshRejected(error: unknown): boolean {
  if (!axios.isAxiosError(error) || !error.response) return false;
  const { status } = error.response;
  return status >= 400 && status < 500 && !isServerUnavailable(status);
}

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
      let tokens: AuthTokens;
      try {
        tokens = await this.refreshTokens();
      } catch (refreshError) {
        // A refused refresh has already expired the session. Otherwise report the outage
        // rather than the 401, so callers that log out on 401 keep the session.
        throw isRefreshRejected(refreshError) ? error : handleError(refreshError);
      }
      originalRequest.headers.Authorization = `Bearer ${tokens.accessToken}`;
      return this.axiosInstance(originalRequest);
    }

    throw error instanceof ApiError
      ? error
      : new ApiError("Request failed", 500);
  }

  private async getValidTokens(): Promise<AuthTokens | null> {
    const tokens = this.config.getTokens();
    if (!tokens) {
      return await this.tryRefreshTokens();
    }

    if (this.isTokenNearExpiry(tokens)) {
      return await this.tryRefreshTokens();
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

  /** One refresh at a time: concurrent callers share it. Rejects when it fails. */
  private refreshTokens(): Promise<AuthTokens> {
    this.refreshPromise ??= this.performTokenRefresh().finally(() => {
      this.refreshPromise = null;
    });
    return this.refreshPromise;
  }

  private async tryRefreshTokens(): Promise<AuthTokens | null> {
    try {
      return await this.refreshTokens();
    } catch {
      return null;
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
    } catch (error) {
      if (isRefreshRejected(error)) {
        this.config.onSessionExpired?.();
      }
      throw error;
    }
  }

  public clearAuth(): void {
    this.config.clearTokens();
  }

  public async getTokens(): Promise<AuthTokens | null> {
    return this.getValidTokens();
  }

  public async refresh(): Promise<AuthTokens | null> {
    return this.tryRefreshTokens();
  }
}
