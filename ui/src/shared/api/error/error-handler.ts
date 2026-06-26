import axios from "axios";
import { ZodError } from "zod";
import { ApiError } from "./errors";

export const handleError = (error: any): ApiError => {
  if (axios.isAxiosError(error)) {
    if (error.response) {
      const { status, data } = error.response;
      const detail = data?.detail;
      const message = Array.isArray(detail)
        ? detail.map((e: any) => e?.msg ?? JSON.stringify(e)).join("; ")
        : detail || data?.message || data?.error || error.message;
      const code = data?.code || `HTTP_${status}`;

      return new ApiError(message, status, code, data, error);
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
