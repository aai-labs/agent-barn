"use client";

import { useState } from "react";

import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";

import { MAX_MODELS_PER_CONNECTION, PRICE_FIELDS } from "../constants";
import { useLlmProviderModelActions } from "../hooks/use-llm-provider-models";
import type {
  LlmProviderCatalogueEntry,
  LlmProviderConnection,
  LlmProviderModel,
  ModelChoice,
  ModelPrices,
} from "../schemas";
import {
  EMPTY_TYPED_PRICES,
  listedPrices,
  perTokenPrices,
  samePrices,
  typedPricesOf,
  typedPricesValid,
} from "../utils";
import { PriceCells, PriceHeaders, PriceNotice, TypedPriceCells } from "./model-price-cells";
import { SaveModelsFooter } from "./save-models-footer";

const MUTED = { color: "var(--ink-3)" };

type Row = {
  entry: LlmProviderCatalogueEntry;
  stored: LlmProviderModel | undefined;
  listed: ModelPrices | null;
  isTicked: boolean;
  isAccepted: boolean;
  typesPrices: boolean;
  typed: ModelPrices;
};

export function ListedModelsPicker({
  connection,
  catalogue,
  storedModels,
  onCancel,
  onSaved,
}: {
  connection: LlmProviderConnection;
  catalogue: LlmProviderCatalogueEntry[];
  storedModels: LlmProviderModel[];
  onCancel: () => void;
  onSaved: () => void;
}) {
  const { saveModels, isSavingModels, saveModelsError } = useLlmProviderModelActions(connection.slug);
  const [ticked, setTicked] = useState(
    () => new Set(catalogue.filter((entry) => entry.stored).map((entry) => entry.modelId)),
  );
  const [accepted, setAccepted] = useState<Set<string>>(() => new Set());
  const [typed, setTyped] = useState<Map<string, ModelPrices>>(() => new Map());
  const [filter, setFilter] = useState("");
  const [leftOut, setLeftOut] = useState(0);

  const storedById = new Map(storedModels.map((model) => [model.modelId, model]));
  const listedIds = new Set(catalogue.map((entry) => entry.modelId));
  const noLongerListed = storedModels.filter((model) => !listedIds.has(model.modelId));
  const rows: Row[] = catalogue.map((entry) => {
    const stored = entry.stored ? storedById.get(entry.modelId) : undefined;
    const listed = listedPrices(entry);
    const isTicked = ticked.has(entry.modelId);
    const isAccepted = accepted.has(entry.modelId) && listed !== null;
    const typesPrices = isTicked && !isAccepted && (listed === null || stored?.priceSource === "manual");
    return {
      entry,
      stored,
      listed,
      isTicked,
      isAccepted,
      typesPrices,
      typed: typed.get(entry.modelId) ?? (stored ? typedPricesOf(stored) : EMPTY_TYPED_PRICES),
    };
  });
  const query = filter.trim().toLowerCase();
  const visible = rows.filter((row) => row.entry.modelId.toLowerCase().includes(query));
  const full = ticked.size >= MAX_MODELS_PER_CONNECTION;
  const pricesMissing = rows.some((row) => row.typesPrices && !typedPricesValid(row.typed));
  const tickable = visible.filter((row) => !row.isTicked && row.listed !== null).map((row) => row.entry.modelId);

  function toggle(modelId: string) {
    setLeftOut(0);
    setTicked((current) => {
      const next = new Set(current);
      if (!next.delete(modelId)) next.add(modelId);
      return next;
    });
  }

  function selectAllPriced() {
    const chosen = tickable.slice(0, MAX_MODELS_PER_CONNECTION - ticked.size);
    setTicked((current) => new Set([...current, ...chosen]));
    setLeftOut(tickable.length - chosen.length);
  }

  function choice(row: Row): ModelChoice {
    const modelId = row.entry.modelId;
    if (row.isAccepted) return { modelId, price: "litellm" };
    if (row.typesPrices) {
      const prices = perTokenPrices(row.typed);
      return row.stored && samePrices(prices, row.stored) ? { modelId, price: "stored" } : { modelId, price: prices };
    }
    return { modelId, price: row.stored ? "stored" : "litellm" };
  }

  async function save() {
    await saveModels(rows.filter((row) => row.isTicked).map(choice))
      .then(onSaved)
      .catch(() => undefined);
  }

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Input
          className="max-w-xs"
          placeholder="Filter by model id…"
          aria-label="Filter models"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
        />
        <div className="flex items-center gap-3">
          {connection.providerType !== "custom" && (
            <button
              type="button"
              className="af-btn af-btn-sm"
              disabled={tickable.length === 0 || full}
              onClick={selectAllPriced}
            >
              Select all priced
            </button>
          )}
          <span className="text-[0.8rem]" style={MUTED}>
            {ticked.size} of {MAX_MODELS_PER_CONNECTION} ticked
          </span>
        </div>
      </div>
      {leftOut > 0 && (
        <p className="m-0 text-[0.8rem]" style={MUTED}>
          The {MAX_MODELS_PER_CONNECTION}-model limit left {leftOut} priced {leftOut === 1 ? "model" : "models"}{" "}
          unticked.
        </p>
      )}
      <div className="max-h-[45vh] overflow-y-auto">
        <table className="w-full border-collapse text-left text-[0.8rem]">
          <thead>
            <tr>
              <th className="py-2 pr-3 font-medium">Model</th>
              <PriceHeaders />
            </tr>
          </thead>
          <tbody>
            {visible.map((row) => (
              <ModelRow
                key={row.entry.modelId}
                row={row}
                canTick={row.isTicked || !full}
                onToggle={() => toggle(row.entry.modelId)}
                onAccept={() => setAccepted((current) => new Set(current).add(row.entry.modelId))}
                onType={(prices) => setTyped((current) => new Map(current).set(row.entry.modelId, prices))}
              />
            ))}
          </tbody>
        </table>
        {visible.length === 0 && (
          <p className="m-0 py-2 text-[0.8rem]" style={MUTED}>
            No models match.
          </p>
        )}
      </div>
      <PriceNotice visible={pricesMissing} />
      {noLongerListed.length > 0 && (
        <section aria-label="Models no longer listed" className="text-[0.8rem]">
          <p className="m-0" style={MUTED}>
            No longer listed by {connection.name}. Saving removes them.
          </p>
          <ul className="m-0 mt-1 pl-5">
            {noLongerListed.map((model) => (
              <li key={model.modelId} className="break-all">
                {model.modelId}
              </li>
            ))}
          </ul>
        </section>
      )}
      <SaveModelsFooter
        error={saveModelsError}
        isSaving={isSavingModels}
        disabled={pricesMissing}
        onCancel={onCancel}
        onSave={() => void save()}
      />
    </>
  );
}

function ModelRow({
  row,
  canTick,
  onToggle,
  onAccept,
  onType,
}: {
  row: Row;
  canTick: boolean;
  onToggle: () => void;
  onAccept: () => void;
  onType: (prices: ModelPrices) => void;
}) {
  const { entry, stored, listed, isTicked, isAccepted, typesPrices, typed } = row;
  const showsChange = Boolean(stored && entry.pricesDiffer && listed && !isAccepted);
  return (
    <tr className="border-t" style={{ borderColor: "var(--line)" }}>
      <td className="py-2 pr-3 align-top">
        <div className="flex items-start gap-2">
          <Checkbox
            className="mt-0.5"
            aria-label={entry.modelId}
            checked={isTicked}
            disabled={!canTick}
            onCheckedChange={onToggle}
          />
          <span className="min-w-0 break-all">
            <span className="block">{entry.modelId}</span>
            {showsChange && (
              <>
                <span className="block text-[0.72rem]" style={MUTED}>
                  LiteLLM&apos;s price has changed
                </span>
                <button
                  type="button"
                  className="af-btn af-btn-sm mt-1"
                  aria-label={`Use LiteLLM's price for ${entry.modelId}`}
                  onClick={onAccept}
                >
                  Use LiteLLM&apos;s price
                </button>
              </>
            )}
            {isAccepted && (
              <span className="block text-[0.72rem]" style={MUTED}>
                Takes LiteLLM&apos;s price when saved
              </span>
            )}
          </span>
        </div>
      </td>
      {typesPrices ? (
        <TypedPriceCells modelId={entry.modelId} prices={typed} onChange={onType} />
      ) : isAccepted && listed ? (
        <PriceCells prices={listed} />
      ) : stored ? (
        <PriceCells prices={stored} listed={showsChange && listed ? listed : undefined} />
      ) : listed ? (
        <PriceCells prices={listed} />
      ) : (
        <td colSpan={PRICE_FIELDS.length} className="py-2 pr-3 text-right align-top" style={MUTED}>
          LiteLLM has no price for this model; tick it to type its prices.
        </td>
      )}
    </tr>
  );
}
