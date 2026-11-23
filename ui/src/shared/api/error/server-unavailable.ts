/**
 * The server gave no answer, or answered "try later": no response (status 0 or none),
 * 5xx, 408 or 429. A request that failed this way says nothing about the session.
 */
export function isServerUnavailable(status: number | undefined): boolean {
  return !status || status >= 500 || status === 408 || status === 429;
}
