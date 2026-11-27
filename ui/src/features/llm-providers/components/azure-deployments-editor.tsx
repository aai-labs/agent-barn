"use client";

import { useRef, useState } from "react";

import { AZURE_DEPLOYMENT_PATTERN, MAX_MODELS_PER_CONNECTION, PRICE_FIELDS } from "../constants";
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
import { RunsModelCombobox } from "./runs-model-combobox";
import { SaveModelsFooter } from "./save-models-footer";

const MUTED = { color: "var(--ink-3)" };
const ERROR = { color: "var(--err)" };
const NAME_RULE = "A deployment name is 1 to 64 letters, digits or . _ - characters.";
const NAME_TAKEN = "Another deployment has this name.";

type Deployment = {
  key: number;
  name: string;
  stored: LlmProviderModel | undefined;
  runsModel: string | null;
  initialRunsModel: string | null;
  other: boolean;
  initialOther: boolean;
  typed: ModelPrices;
  accepted: boolean;
};

export function AzureDeploymentsEditor({
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
  const listed = new Map(
    catalogue.flatMap((entry) => {
      const prices = listedPrices(entry);
      return prices ? [[entry.modelId, { key: entry.litellmPriceKey, prices }] as const] : [];
    }),
  );
  const models = [...listed.keys()];
  const nextKey = useRef(storedModels.length);
  const [deployments, setDeployments] = useState<Deployment[]>(() =>
    storedModels.map((stored, key) => {
      const runsModel =
        stored.priceSource === "litellm"
          ? (models.find((model) => listed.get(model)?.key === stored.litellmPriceKey) ?? null)
          : null;
      const other = runsModel === null;
      return {
        key,
        name: stored.modelId,
        stored,
        runsModel,
        initialRunsModel: runsModel,
        other,
        initialOther: other,
        typed: other ? typedPricesOf(stored) : EMPTY_TYPED_PRICES,
        accepted: false,
      };
    }),
  );

  const nameCounts = new Map<string, number>();
  for (const deployment of deployments) {
    nameCounts.set(deployment.name, (nameCounts.get(deployment.name) ?? 0) + 1);
  }
  const nameProblem = (deployment: Deployment) =>
    !AZURE_DEPLOYMENT_PATTERN.test(deployment.name)
      ? NAME_RULE
      : (nameCounts.get(deployment.name) ?? 0) > 1
        ? NAME_TAKEN
        : null;
  const pricesMissing = deployments.some((deployment) => deployment.other && !typedPricesValid(deployment.typed));
  const unready = deployments.some(
    (deployment) => nameProblem(deployment) !== null || (!deployment.other && deployment.runsModel === null),
  );

  function update(key: number, change: Partial<Deployment>) {
    setDeployments((current) =>
      current.map((deployment) => (deployment.key === key ? { ...deployment, ...change } : deployment)),
    );
  }

  function add() {
    const key = nextKey.current++;
    setDeployments((current) => [
      ...current,
      {
        key,
        name: "",
        stored: undefined,
        runsModel: null,
        initialRunsModel: null,
        other: false,
        initialOther: false,
        typed: EMPTY_TYPED_PRICES,
        accepted: false,
      },
    ]);
  }

  function choice(deployment: Deployment): ModelChoice {
    const { name: modelId, stored } = deployment;
    if (deployment.other) {
      const prices = perTokenPrices(deployment.typed);
      return deployment.initialOther && stored && samePrices(prices, stored)
        ? { modelId, price: "stored" }
        : { modelId, price: prices };
    }
    const runsModel = deployment.runsModel ?? "";
    return stored && !deployment.initialOther && runsModel === deployment.initialRunsModel && !deployment.accepted
      ? { modelId, price: "stored" }
      : { modelId, price: "litellm", runsModel };
  }

  async function save() {
    await saveModels(deployments.map(choice))
      .then(onSaved)
      .catch(() => undefined);
  }

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <button
          type="button"
          className="af-btn af-btn-sm"
          disabled={deployments.length >= MAX_MODELS_PER_CONNECTION}
          onClick={add}
        >
          Add deployment
        </button>
        <span className="text-[0.8rem]" style={MUTED}>
          {deployments.length} of {MAX_MODELS_PER_CONNECTION} deployments
        </span>
      </div>
      {/* Below the table's width, it scrolls sideways rather than squeeze names into a few letters a line. */}
      <div className="max-h-[45vh] overflow-auto">
        <table className="w-full min-w-[48rem] border-collapse text-left text-[0.8rem]">
          <thead>
            <tr>
              <th className="py-2 pr-3 font-medium">Deployment</th>
              <th className="py-2 pr-3 font-medium">Runs model</th>
              <PriceHeaders />
              <th className="py-2 font-medium">
                <span className="sr-only">Remove</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {deployments.map((deployment, index) => {
              // A new row has no name yet; its position tells it apart for a screen reader.
              const rowName = deployment.name.trim() || `new deployment ${index + 1}`;
              const runs = deployment.runsModel ? listed.get(deployment.runsModel)?.prices : undefined;
              const keepsStored =
                deployment.stored &&
                !deployment.initialOther &&
                deployment.runsModel === deployment.initialRunsModel &&
                !deployment.accepted;
              const showsChange = Boolean(
                keepsStored && deployment.stored && runs && !samePrices(deployment.stored, runs),
              );
              const problem = deployment.stored ? null : nameProblem(deployment);
              return (
                <tr key={deployment.key} className="border-t" style={{ borderColor: "var(--line)" }}>
                  <td className="py-2 pr-3 align-top">
                    {deployment.stored ? (
                      <span className="block min-w-0 break-words">
                        <span className="block">{deployment.name}</span>
                        {showsChange && (
                          <>
                            <span className="block text-[0.72rem]" style={MUTED}>
                              LiteLLM&apos;s price has changed
                            </span>
                            <button
                              type="button"
                              className="af-btn af-btn-sm mt-1"
                              aria-label={`Use LiteLLM's price for ${deployment.name}`}
                              onClick={() => update(deployment.key, { accepted: true })}
                            >
                              Use LiteLLM&apos;s price
                            </button>
                          </>
                        )}
                        {deployment.accepted && (
                          <span className="block text-[0.72rem]" style={MUTED}>
                            Takes LiteLLM&apos;s price when saved
                          </span>
                        )}
                      </span>
                    ) : (
                      <>
                        <input
                          className="af-input w-40"
                          aria-label={`New deployment ${index + 1} name`}
                          aria-invalid={problem !== null}
                          value={deployment.name}
                          onChange={(event) => update(deployment.key, { name: event.target.value })}
                        />
                        {problem && (
                          <span className="block text-[0.72rem]" style={ERROR}>
                            {problem}
                          </span>
                        )}
                      </>
                    )}
                  </td>
                  <td className="py-2 pr-3 align-top">
                    <RunsModelCombobox
                      label={`Model ${rowName} runs`}
                      models={models}
                      runsModel={deployment.runsModel}
                      other={deployment.other}
                      onChoose={(runsModel) =>
                        update(deployment.key, { runsModel, other: runsModel === null, accepted: false })
                      }
                    />
                  </td>
                  {deployment.other ? (
                    <TypedPriceCells
                      modelId={rowName}
                      prices={deployment.typed}
                      onChange={(typed) => update(deployment.key, { typed })}
                    />
                  ) : keepsStored && deployment.stored ? (
                    <PriceCells prices={deployment.stored} listed={showsChange ? runs : undefined} />
                  ) : runs ? (
                    <PriceCells prices={runs} />
                  ) : (
                    <td colSpan={PRICE_FIELDS.length} className="py-2 pr-3 text-right align-top" style={MUTED}>
                      Choose the model it runs.
                    </td>
                  )}
                  <td className="py-2 align-top">
                    <button
                      type="button"
                      className="af-btn af-btn-sm"
                      aria-label={`Remove ${rowName}`}
                      onClick={() =>
                        setDeployments((current) => current.filter((row) => row.key !== deployment.key))
                      }
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {deployments.length === 0 && (
          <p className="m-0 py-2 text-[0.8rem]" style={MUTED}>
            No deployments yet.
          </p>
        )}
      </div>
      <PriceNotice visible={pricesMissing} />
      <SaveModelsFooter
        error={saveModelsError}
        isSaving={isSavingModels}
        disabled={pricesMissing || unready}
        onCancel={onCancel}
        onSave={() => void save()}
      />
    </>
  );
}
