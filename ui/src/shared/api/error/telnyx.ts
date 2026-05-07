import {
  getIntegrationServiceUnavailableDetails,
  INTEGRATION_SERVICE_UNAVAILABLE_CODE,
  isIntegrationServiceUnavailable,
} from "./integration";

export const TELNYX_SERVICE_UNAVAILABLE_CODE =
  INTEGRATION_SERVICE_UNAVAILABLE_CODE.telnyx;

export const isTelnyxServiceUnavailable = (error: unknown): boolean =>
  isIntegrationServiceUnavailable(error, "telnyx");

export const getTelnyxServiceUnavailableDetails = (
  errors: unknown[],
): { message: string | null; eventId: string | null } => {
  return getIntegrationServiceUnavailableDetails(errors, "telnyx");
};
