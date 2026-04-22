import { AxiosError } from "axios";

export class ApiError extends Error {
  public readonly status: number;
  public readonly code: string;
  public readonly details?: any;
  public readonly timestamp: string;
  public readonly internalError?: AxiosError;

  constructor(
    message: string,
    status: number,
    code: string = "UNKNOWN_ERROR",
    details?: any,
    internalError?: AxiosError,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.timestamp = new Date().toISOString();
    this.internalError = internalError;
  }

  static networkError(message: string = "Network error occurred"): ApiError {
    return new ApiError(message, 0, "NETWORK_ERROR");
  }

  static validationError(message: string, details?: any): ApiError {
    return new ApiError(message, 400, "VALIDATION_ERROR", details);
  }

  static unauthorizedError(message: string = "Unauthorized"): ApiError {
    return new ApiError(message, 401, "UNAUTHORIZED");
  }

  static forbiddenError(message: string = "Forbidden"): ApiError {
    return new ApiError(message, 403, "FORBIDDEN");
  }

  static notFoundError(message: string = "Resource not found"): ApiError {
    return new ApiError(message, 404, "NOT_FOUND");
  }

  static serverError(message: string = "Internal server error"): ApiError {
    return new ApiError(message, 500, "SERVER_ERROR");
  }
}
