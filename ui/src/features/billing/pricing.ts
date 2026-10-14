/** What `creditUsd` of credit costs: the credit at the platform's rate plus its purchase
 *  fee, rounded up to the cent. The API computes the same; this is only the preview. */
export function chargeUsd(creditUsd: number, { creditRate, purchaseFeePercent }: { creditRate: number; purchaseFeePercent: number }) {
  const dollars = (creditUsd / creditRate) * (1 + purchaseFeePercent / 100);
  // A float epsilon must not round an exact cent up.
  return Math.ceil(Math.round(dollars * 100 * 1e6) / 1e6) / 100;
}
