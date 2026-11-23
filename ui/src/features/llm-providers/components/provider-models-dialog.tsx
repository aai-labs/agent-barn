"use client";

import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";

import { useLlmProviderModels } from "../hooks/use-llm-provider-models";
import type { LlmProviderConnection } from "../schemas";
import { failureMessage } from "../utils";
import { AzureDeploymentsEditor } from "./azure-deployments-editor";
import { ListedModelsPicker } from "./listed-models-picker";

const ERROR = { color: "var(--err)" };

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
  const isAzure = connection.providerType === "azure";
  const Editor = isAzure ? AzureDeploymentsEditor : ListedModelsPicker;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle>
            {connection.name} {isAzure ? "deployments" : "models"}
          </DialogTitle>
          <DialogDescription>
            {isAzure
              ? "Agents can use these deployments. A deployment takes the price of the model it runs, or the prices you type. Prices are per 1M tokens."
              : "Agents can use the ticked models. A newly ticked model takes LiteLLM's price, or the prices you type when LiteLLM has none; a stored one keeps its own. Prices are per 1M tokens."}
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
          <Editor
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
