import { ApiError } from "./errors";

export type ErrorDisplay = {
  title: string;
  description: string;
};

export function getErrorDisplay(
  error: unknown,
  fallback: ErrorDisplay = {
    title: "Something went wrong",
    description: "Please try again in a moment.",
  },
): ErrorDisplay {
  if (error instanceof ApiError) {
    if (error.status === 0) {
      return {
        title: "Network error",
        description:
          "We couldn't reach the server. Check your connection and try again.",
      };
    }

    if (error.status === 401) {
      return {
        title: "Your session has expired",
        description: "Please sign in again to continue.",
      };
    }

    if (error.status === 403) {
      return {
        title: "Access denied",
        description: "You do not have permission to view this content.",
      };
    }

    if (error.status === 404) {
      return {
        title: "Not found",
        description: "We couldn't find the information you requested.",
      };
    }

    if (error.status >= 500) {
      return {
        title: "Server error",
        description:
          error.message || "The server hit a problem while loading this page.",
      };
    }

    return {
      title: "Request failed",
      description: error.message || fallback.description,
    };
  }

  if (error instanceof Error) {
    return {
      title: fallback.title,
      description: error.message || fallback.description,
    };
  }

  return fallback;
}
