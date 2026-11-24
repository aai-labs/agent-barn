"use client";

import { PRICE_FIELDS } from "../constants";
import type { ModelPrices } from "../schemas";
import { perMillion, samePrice, typedPriceValid } from "../utils";

const MUTED = { color: "var(--ink-3)" };
const CELL_CLASS = "py-2 pr-3 text-right align-top tabular-nums";

export function PriceHeaders() {
  return PRICE_FIELDS.map(({ column }) => (
    <th key={column} className="py-2 pr-3 text-right font-medium">
      {column}
    </th>
  ));
}

export function PriceCells({ prices, listed }: { prices: ModelPrices; listed?: ModelPrices }) {
  return PRICE_FIELDS.map(({ field, column }) => (
    <td key={column} className={CELL_CLASS}>
      ${perMillion(prices[field])}
      {listed && !samePrice(prices[field], listed[field]) && (
        <span className="block text-[0.72rem]" style={MUTED}>
          LiteLLM ${perMillion(listed[field])}
        </span>
      )}
    </td>
  ));
}

export function TypedPriceCells({
  modelId,
  prices,
  onChange,
}: {
  modelId: string;
  prices: ModelPrices;
  onChange: (prices: ModelPrices) => void;
}) {
  return PRICE_FIELDS.map(({ field, column }) => (
    <td key={column} className={CELL_CLASS}>
      <input
        className="af-input w-20 text-right"
        inputMode="decimal"
        aria-label={`${modelId} ${column} price per 1M tokens`}
        aria-invalid={!typedPriceValid(field, prices[field])}
        value={prices[field]}
        onChange={(event) => onChange({ ...prices, [field]: event.target.value })}
      />
    </td>
  ));
}

export function PriceNotice({ visible }: { visible: boolean }) {
  if (!visible) return null;
  return (
    <p className="m-0 text-[0.8rem]" style={MUTED}>
      Type each price in dollars per 1M tokens, with at most 12 decimal places: input and output above 0, cache 0 or
      more.
    </p>
  );
}
