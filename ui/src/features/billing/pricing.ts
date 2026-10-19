/** What `creditUsd` of credit costs: the credit plus the purchase fee, rounded up to the
 *  cent. The API computes the same; this is only the preview. */
export function chargeUsd(creditUsd: number, { purchaseFeePercent }: { purchaseFeePercent: number }) {
  const dollars = creditUsd * (1 + purchaseFeePercent / 100);
  // A float epsilon must not round an exact cent up.
  return Math.ceil(Math.round(dollars * 100 * 1e6) / 1e6) / 100;
}
