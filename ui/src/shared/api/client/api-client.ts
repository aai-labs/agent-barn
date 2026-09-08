import axios from "axios";
import {
  createRequestInterceptor,
  createResponseInterceptor,
} from "../interceptor/default";
import { validateResponse } from "../utils";
import { handleError } from "../error/error-handler";
import { ApiError } from "../error/errors";
import { AuthInterceptor } from "../interceptor/auth-intercepter";
import type { AxiosInstance, AxiosRequestConfig, AxiosResponse } from "axios";
import type {
  ApiClientConfig,
  ApiResult,
  AuthConfig,
  RequestOptions,
} from "../types";

type ApiRequestConfig = AxiosRequestConfig & {
  skipAuth?: boolean;
};

export class ApiClient {
  private axiosInstance: AxiosInstance;
  private config: Required<ApiClientConfig>;
  private authInterceptor?: AuthInterceptor;

  constructor(config: ApiClientConfig) {
    this.config = config as Required<ApiClientConfig>;
    this.axiosInstance = axios.create({
      baseURL: this.config.baseURL,
      timeout: this.config.timeout,
      withCredentials: true,
      headers: {
        "Content-Type": "application/json",
        ...this.config.headers,
      },
    });

    this.setupInterceptors();
  }

  setupAuth(authConfig: AuthConfig): void {
    this.authInterceptor = new AuthInterceptor(this.axiosInstance, authConfig);
  }

  clearAuth(): void {
    this.authInterceptor?.clearAuth();
  }

  async getAuthHeaders(forceRefresh = false): Promise<Record<string, string>> {
    const tokens = forceRefresh
      ? await this.authInterceptor?.refresh()
      : await this.authInterceptor?.getTokens();
    return tokens?.accessToken
      ? { Authorization: `Bearer ${tokens.accessToken}` }
      : {};
  }

  private setupInterceptors(): void {
    const requestInterceptor = createRequestInterceptor(
      this.config.transformKeys,
    );
    const responseInterceptor = createResponseInterceptor(
      this.config.transformKeys,
    );

    this.axiosInstance.interceptors.request.use(
      requestInterceptor.onFulfilled,
      requestInterceptor.onRejected,
    );

    this.axiosInstance.interceptors.response.use(
      responseInterceptor.onFulfilled,
      responseInterceptor.onRejected,
    );
  }

  private async makeRequest<T = any>(
    method: string,
    url: string,
    options: RequestOptions<T> = {},
  ): Promise<ApiResult<T>> {
    const { data, schema, headers, signal, skipAuth, ...axiosConfig } = options;

    try {
      const isFormData = data instanceof FormData;
      const requestHeaders = isFormData
        ? {
            "Content-Type": "application/x-www-form-urlencoded",
            ...headers,
          }
        : headers;

      const requestConfig: ApiRequestConfig = {
        method,
        url,
        data,
        headers: requestHeaders,
        signal,
        skipAuth,
        ...axiosConfig,
      };

      const response: AxiosResponse = await this.axiosInstance(requestConfig);
      let responseData = response.data;
      if (schema) {
        responseData = await validateResponse(responseData, schema);
      }

      return {
        data: responseData,
        status: response.status,
        message: response.statusText,
        headers: response.headers,
      };
    } catch (error) {
      throw error instanceof ApiError ? error : handleError(error);
    }
  }

  async get<T = any>(
    url: string,
    options: RequestOptions<T> = {},
  ): Promise<ApiResult<T>> {
    return this.makeRequest<T>("GET", url, options);
  }

  async uploadFile<T = any>(
    url: string,
    file: File,
    fieldName: string = "file",
    options: RequestOptions<T> = {},
  ): Promise<ApiResult<T>> {
    const formData = new FormData();
    formData.append(fieldName, file);

    return this.makeRequest<T>("POST", url, {
      ...options,
      headers: {
        ...options.headers,
        "Content-Type": undefined,
      } as any,
      data: formData,
    });
  }

  async getFile(
    url: string,
    options: Omit<RequestOptions<Blob>, "schema"> = {},
  ): Promise<ApiResult<Blob>> {
    const { headers, ...restOptions } = options;

    const cleanHeaders = { ...headers } as Record<string, any>;
    delete cleanHeaders["Content-Type"];

    return this.makeRequest<Blob>("GET", url, {
      ...restOptions,
      responseType: "blob",
      headers: cleanHeaders,
      timeout: options.timeout || 60000,
    });
  }

  async post<T = any>(
    url: string,
    data?: any,
    options: RequestOptions<T> = {},
  ): Promise<ApiResult<T>> {
    return this.makeRequest<T>("POST", url, { ...options, data });
  }

  async put<T = any>(
    url: string,
    data?: any,
    options: RequestOptions<T> = {},
  ): Promise<ApiResult<T>> {
    return this.makeRequest<T>("PUT", url, { ...options, data });
  }

  async patch<T = any>(
    url: string,
    data?: any,
    options: RequestOptions<T> = {},
  ): Promise<ApiResult<T>> {
    return this.makeRequest<T>("PATCH", url, { ...options, data });
  }

  async delete<T = any>(
    url: string,
    options: RequestOptions<T> = {},
  ): Promise<ApiResult<T>> {
    return this.makeRequest<T>("DELETE", url, options);
  }

  async head(
    url: string,
    options: RequestOptions = {},
  ): Promise<ApiResult<void>> {
    return this.makeRequest<void>("HEAD", url, options);
  }

  async options(
    url: string,
    options: RequestOptions = {},
  ): Promise<ApiResult<any>> {
    return this.makeRequest("OPTIONS", url, options);
  }

  setHeader(key: string, value: string): void {
    this.axiosInstance.defaults.headers.common[key] = value;
  }

  removeHeader(key: string): void {
    delete this.axiosInstance.defaults.headers.common[key];
  }

  getConfig(): Required<ApiClientConfig> {
    return { ...this.config };
  }

  updateConfig(newConfig: Partial<ApiClientConfig>): void {
    this.config = { ...this.config, ...newConfig };

    if (newConfig.baseURL) {
      this.axiosInstance.defaults.baseURL = newConfig.baseURL;
    }
    if (newConfig.timeout) {
      this.axiosInstance.defaults.timeout = newConfig.timeout;
    }
    if (newConfig.headers) {
      Object.assign(
        this.axiosInstance.defaults.headers.common,
        newConfig.headers,
      );
    }
  }
}
