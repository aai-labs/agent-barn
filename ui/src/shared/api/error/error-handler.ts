import axios from "axios";
import { ZodError } from "zod";
import { ApiError } from "./errors";

// FastAPI sends `detail` as a string, a list of validation errors, or an object
// such as a classified provisioning failure or an agent health report.
const isDetailObject = (detail: unknown): detail is Record<string, any> =>
  typeof detail === "object" && detail !== null && !Array.isArray(detail);

const messageFrom = (data: any, fallback: string): string => {
  const detail = data?.detail;

  if (Array.isArray(detail)) {
    return detail.map((item: any) => item?.msg ?? JSON.stringify(item)).join("; ");
  }
  if (isDetailObject(detail)) {
    return detail.summary || detail.message || detail.reason || fallback;
  }
  return detail || data?.message || data?.error || fallback;
};

const codeFrom = (data: any, status: number): string => {
  const detail = data?.detail;
  const detailCode = isDetailObject(detail) ? detail.code : undefined;

  return detailCode || data?.code || `HTTP_${status}`;
};

export const handleError = (error: any): ApiError => {
  if (axios.isAxiosError(error)) {
    if (error.response) {
      const { status, data } = error.response;

      return new ApiError(
        messageFrom(data, error.message),
        status,
        codeFrom(data, status),
        data,
        error,
      );
    } else if (error.request) {
      return ApiError.networkError(error.message);
    }
  }

  if (error instanceof ZodError) {
    return ApiError.validationError("Response validation failed", {
      zodErrors: error.issues,
    });
  }

  return new ApiError(
    error.message || "Unknown error occurred",
    500,
    "UNKNOWN_ERROR",
  );
};
