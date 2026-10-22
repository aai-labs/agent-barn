/** The credit an organization had when its owner left to pay, kept in this tab for the
 *  trip to the payment page and back. Coming back, the page compares against it: the
 *  purchase has often landed before the first read, so that read can't be the baseline. */

const key = (organizationId: string) => `billing:credit-before-checkout:${organizationId}`;

export function rememberCreditBeforeCheckout(organizationId: string, creditUsd: number) {
  try {
    sessionStorage.setItem(key(organizationId), String(creditUsd));
  } catch {
    // Storage unavailable: the return falls back to its first read.
  }
}

/** The remembered credit, once: it is forgotten as it is read. */
export function takeCreditBeforeCheckout(organizationId: string): number | null {
  try {
    const stored = sessionStorage.getItem(key(organizationId));
    sessionStorage.removeItem(key(organizationId));
    const value = stored ? Number(stored) : Number.NaN;
    return Number.isFinite(value) ? value : null;
  } catch {
    return null;
  }
}
