"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";

import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";

import { MAX_MODELS_PER_CONNECTION } from "../constants";
import { useLlmProviderModelActions, useLlmProviderModels } from "../hooks/use-llm-provider-models";
import type { LlmProviderCatalogueEntry, LlmProviderConnection, LlmProviderModel, ModelChoice } from "../schemas";
import { failureMessage, perMillion } from "../utils";

const MUTED = { color: "var(--ink-3)" };
const ERROR = { color: "var(--err)" };
const PRICE_COLUMNS = ["Input", "Output", "Cache read", "Cache write"];

type Prices = Pick<
  LlmProviderModel,
  "inputCostPerToken" | "outputCostPerToken" | "cacheReadInputTokenCost" | "cacheCreationInputTokenCost"
>;

export function ProviderModelsDialog({
  connection,
  open,
  onOpenChange,
  onSaved,
}: {
  connection: LlmProviderConnection;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
}) {
  const { storedModels, catalogue, isLoadingModels, modelsError, reloadModels } = useLlmProviderModels(
    connection.slug,
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{connection.name} models</DialogTitle>
          <DialogDescription>
            Agents can use the ticked models. Prices are per 1M tokens; a newly ticked model takes LiteLLM&apos;s
            price, and a stored one keeps its own.
          </DialogDescription>
        </DialogHeader>
        {isLoadingModels ? (
          <p role="status" className="m-0 text-sm">
            Loading models…
          </p>
        ) : modelsError || !catalogue || !storedModels ? (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="m-0 text-[0.8rem]" style={ERROR} role="alert">
              {failureMessage(modelsError)}
            </p>
            <button type="button" className="af-btn af-btn-sm" onClick={() => void reloadModels()}>
              Retry
            </button>
          </div>
        ) : (
          <ModelPicker
            connection={connection}
            catalogue={catalogue}
            storedModels={storedModels}
            onCancel={() => onOpenChange(false)}
            onSaved={onSaved}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

function ModelPicker({
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
  const [filter, setFilter] = useState("");

  const stored = new Map(storedModels.map((model) => [model.modelId, model]));
  const listed = new Set(catalogue.map((entry) => entry.modelId));
  const noLongerListed = storedModels.filter((model) => !listed.has(model.modelId));
  const query = filter.trim().toLowerCase();
  const visible = catalogue.filter((entry) => entry.modelId.toLowerCase().includes(query));
  const full = ticked.size >= MAX_MODELS_PER_CONNECTION;

  function toggle(modelId: string) {
    setTicked((current) => {
      const next = new Set(current);
      if (!next.delete(modelId)) next.add(modelId);
      return next;
    });
  }

  async function save() {
    const models: ModelChoice[] = catalogue
      .filter((entry) => ticked.has(entry.modelId))
      .map((entry) => ({ modelId: entry.modelId, price: entry.stored ? "stored" : "litellm" }));
    await saveModels(models)
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
        <span className="text-[0.8rem]" style={MUTED}>
          {ticked.size} of {MAX_MODELS_PER_CONNECTION} ticked
        </span>
      </div>
      <div className="max-h-[45vh] overflow-y-auto">
        <table className="w-full border-collapse text-left text-[0.8rem]">
          <thead>
            <tr>
              <th className="py-2 pr-3 font-medium">Model</th>
              {PRICE_COLUMNS.map((column) => (
                <th key={column} className="py-2 pr-3 text-right font-medium">
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((entry) => {
              const storedModel = entry.stored ? stored.get(entry.modelId) : undefined;
              const prices = storedModel ?? listedPrices(entry);
              const isTicked = ticked.has(entry.modelId);
              return (
                <tr key={entry.modelId} className="border-t" style={{ borderColor: "var(--line)" }}>
                  <td className="py-2 pr-3">
                    <label className="flex items-start gap-2">
                      <Checkbox
                        className="mt-0.5"
                        aria-label={entry.modelId}
                        checked={isTicked}
                        disabled={(!prices && !entry.stored) || (!isTicked && full)}
                        onCheckedChange={() => toggle(entry.modelId)}
                      />
                      <span className="min-w-0 break-all">
                        <span className="block">{entry.modelId}</span>
                        {entry.stored && entry.pricesDiffer && (
                          <span className="block text-[0.72rem]" style={MUTED}>
                            LiteLLM&apos;s price has changed
                          </span>
                        )}
                      </span>
                    </label>
                  </td>
                  {prices ? (
                    priceCells(prices)
                  ) : (
                    <td colSpan={PRICE_COLUMNS.length} className="py-2 pr-3 text-right" style={MUTED}>
                      LiteLLM has no price for this model.
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
        {visible.length === 0 && (
          <p className="m-0 py-2 text-[0.8rem]" style={MUTED}>
            No models match.
          </p>
        )}
      </div>
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
      {saveModelsError ? (
        <p className="m-0 text-[0.8rem]" style={ERROR} role="alert">
          {failureMessage(saveModelsError)}
        </p>
      ) : null}
      <DialogFooter>
        <button type="button" className="af-btn" onClick={onCancel}>
          Cancel
        </button>
        <button type="button" className="af-btn af-btn-primary" disabled={isSavingModels} onClick={() => void save()}>
          {isSavingModels && <Loader2 size={14} className="animate-spin" />} Save models
        </button>
      </DialogFooter>
    </>
  );
}

function listedPrices(entry: LlmProviderCatalogueEntry): Prices | null {
  const { inputCostPerToken, outputCostPerToken, cacheReadInputTokenCost, cacheCreationInputTokenCost } = entry;
  if (
    inputCostPerToken === null ||
    outputCostPerToken === null ||
    cacheReadInputTokenCost === null ||
    cacheCreationInputTokenCost === null
  )
    return null;
  return { inputCostPerToken, outputCostPerToken, cacheReadInputTokenCost, cacheCreationInputTokenCost };
}

function priceCells(prices: Prices) {
  return [
    prices.inputCostPerToken,
    prices.outputCostPerToken,
    prices.cacheReadInputTokenCost,
    prices.cacheCreationInputTokenCost,
  ].map((price, index) => (
    <td key={PRICE_COLUMNS[index]} className="py-2 pr-3 text-right tabular-nums">
      ${perMillion(price)}
    </td>
  ));
}
