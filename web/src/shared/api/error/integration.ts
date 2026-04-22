import { ApiError } from "./errors";

export type IntegrationProvider = "telnyx";

export const INTEGRATION_SERVICE_UNAVAILABLE_CODE: Record<
  IntegrationProvider,
  string
> = {
  telnyx: "TELNYX_SERVICE_UNAVAILABLE",
};

const INTEGRATION_SERVICE_UNAVAILABLE_MESSAGE: Record<
  IntegrationProvider,
  string
> = {
  telnyx: "Telnyx service appears to be unavailable. Please try again later.",
};

export interface IntegrationServiceUnavailableDetails {
  message: string | null;
  eventId: string | null;
}

export function isIntegrationServiceUnavailable(
  error: unknown,
  provider: IntegrationProvider,
): boolean {
  return (
    error instanceof ApiError &&
    error.code === INTEGRATION_SERVICE_UNAVAILABLE_CODE[provider]
  );
}

export function getIntegrationServiceUnavailableDetails(
  errors: unknown[],
  provider: IntegrationProvider,
): IntegrationServiceUnavailableDetails {
  for (const error of errors) {
    if (isIntegrationServiceUnavailable(error, provider)) {
      const apiError = error as ApiError;
      const details = apiError.details;
      const eventId = details?.event_id || details?.eventId;
      return {
        // Keep provider outage copy concise and predictable across UIs.
        message: INTEGRATION_SERVICE_UNAVAILABLE_MESSAGE[provider],
        eventId:
          typeof eventId === "string" && eventId.length > 0 ? eventId : null,
      };
    }
  }

  return { message: null, eventId: null };
}
