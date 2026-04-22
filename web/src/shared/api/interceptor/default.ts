import { camelizeKeys, decamelizeKeys } from "humps";
import { handleError } from "../error/error-handler";
import { AxiosResponse, InternalAxiosRequestConfig } from "axios";

function safeCamelizeKeys(obj: any) {
  return camelizeKeys(obj, (key, convert) => {
    if (key.includes("-")) return key;
    return convert(key);
  });
}

function safeDecamelizeKeys(obj: any) {
  return decamelizeKeys(obj, (key, convert) => {
    if (key.includes("-")) return key;
    return convert(key);
  });
}

export const createRequestInterceptor = (transformKeys: boolean) => ({
  onFulfilled: (config: InternalAxiosRequestConfig) => {
    if (
      transformKeys &&
      config.data &&
      !(config.data instanceof FormData) &&
      !(config.data instanceof Blob)
    ) {
      config.data = safeDecamelizeKeys(config.data);
    }
    return config;
  },
  onRejected: (error: any) => Promise.reject(handleError(error)),
});

export const createResponseInterceptor = (transformKeys: boolean) => ({
  onFulfilled: (response: AxiosResponse) => {
    if (
      transformKeys &&
      response.data &&
      !(response.data instanceof Blob) &&
      !(response.data instanceof ArrayBuffer) &&
      !(response.data instanceof FormData)
    ) {
      response.data = safeCamelizeKeys(response.data);
    }
    return response;
  },
  onRejected: (error: any) => Promise.reject(handleError(error)),
});
