"use client";

import { useState } from "react";
import { Plus } from "lucide-react";
import { toast } from "sonner";

import { AppErrorState } from "@/components/app-error-state";
import { ConfirmationDialog } from "@/components/confirmation-dialog";

import { BASE_URL_PROVIDER_TYPES, KNOWN_PROVIDER_TYPES } from "../constants";
import { useLlmProviderActions, useLlmProviderConnections } from "../hooks/use-llm-provider-connections";
import type { KeyReplacement, LlmProviderConnection, NewLlmProviderConnection } from "../schemas";
import { failureMessage } from "../utils";
import { AddLlmProviderDialog } from "./add-llm-provider-dialog";
import { DeploymentProviderCard } from "./deployment-provider-card";
import { ProviderCard } from "./provider-card";
import { ProviderKeyDialog } from "./provider-key-dialog";
import { ProviderModelsDialog } from "./provider-models-dialog";

export function PlatformLlmProviderSettings() {
  const { connections, isLoadingConnections, connectionsError, reloadConnections } = useLlmProviderConnections();
  const {
    addConnection,
    isAdding,
    addError,
    resetAdd,
    replaceKey,
    isReplacing,
    replaceError,
    resetReplace,
    deleteConnection,
    isDeleting,
    deleteError,
    resetDelete,
  } = useLlmProviderActions();
  const [addOpen, setAddOpen] = useState(false);
  const [addKey, setAddKey] = useState(0);
  const [keyTarget, setKeyTarget] = useState<LlmProviderConnection | null>(null);
  const [keyOpen, setKeyOpen] = useState(false);
  const [keyDialogKey, setKeyDialogKey] = useState(0);
  const [deleting, setDeleting] = useState<LlmProviderConnection | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [modelsTarget, setModelsTarget] = useState<LlmProviderConnection | null>(null);
  const [modelsOpen, setModelsOpen] = useState(false);
  const [modelsDialogKey, setModelsDialogKey] = useState(0);

  if (isLoadingConnections) return <p role="status">Loading LLM provider settings…</p>;
  if (connectionsError || !connections)
    return (
      <AppErrorState
        error={connectionsError}
        title="Could not load LLM provider settings"
        onRetry={() => void reloadConnections()}
      />
    );

  const connected = new Set(connections.map((connection) => connection.providerType));
  const available = [...KNOWN_PROVIDER_TYPES.filter((type) => !connected.has(type)), ...BASE_URL_PROVIDER_TYPES];
  const deployment = connections.find(
    (connection) => connection.providerType === "openrouter" && connection.envKeyConfigured,
  );
  const listed = connections.filter((connection) => connection !== deployment);

  function openAdd() {
    resetAdd();
    setAddKey((current) => current + 1);
    setAddOpen(true);
  }

  async function add(connection: NewLlmProviderConnection) {
    const saved = await addConnection(connection);
    setAddOpen(false);
    toast.success(`${saved.name} added`);
  }

  function openKeyDialog(connection: LlmProviderConnection) {
    resetReplace();
    setKeyTarget(connection);
    setKeyDialogKey((current) => current + 1);
    setKeyOpen(true);
  }

  async function save(slug: string, replacement: KeyReplacement) {
    const saved = await replaceKey({ slug, ...replacement });
    setKeyOpen(false);
    toast.success(`${saved.name} key saved`);
  }

  function openModels(connection: LlmProviderConnection) {
    setModelsTarget(connection);
    setModelsDialogKey((current) => current + 1);
    setModelsOpen(true);
  }

  function modelsSaved(connection: LlmProviderConnection) {
    setModelsOpen(false);
    toast.success(`${connection.name} models saved`);
  }

  function openDelete(connection: LlmProviderConnection) {
    resetDelete();
    setDeleting(connection);
    setDeleteOpen(true);
  }

  async function confirmDelete(connection: LlmProviderConnection) {
    await deleteConnection(connection.slug);
    setDeleteOpen(false);
    toast.success(`${connection.name} deleted`);
  }

  return (
    <>
      {deployment && (
        <section aria-labelledby="llm-providers-deployment-heading" className="mb-6">
          <h2 id="llm-providers-deployment-heading" className="mb-3 mt-0 text-[0.95rem] font-semibold">
            Set by this deployment
          </h2>
          <DeploymentProviderCard connection={deployment} onReplaceKey={() => openKeyDialog(deployment)} />
        </section>
      )}

      <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
        <p className="m-0 min-w-0 flex-1 basis-[24rem] text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
          Each key is checked with its provider before it is saved, and only its last four characters are shown.
        </p>
        <button type="button" className="af-btn af-btn-sm" onClick={openAdd}>
          <Plus size={14} /> Add provider
        </button>
      </div>

      <ul aria-label="LLM providers" className="m-0 flex list-none flex-col gap-3 p-0">
        {listed.map((connection) => (
          <li key={connection.slug}>
            <ProviderCard
              connection={connection}
              onReplaceKey={() => openKeyDialog(connection)}
              onModels={
                connection.hasApiKey && connection.providerType !== "openrouter"
                  ? () => openModels(connection)
                  : undefined
              }
              onDelete={connection.providerType === "openrouter" ? undefined : () => openDelete(connection)}
            />
          </li>
        ))}
      </ul>

      <AddLlmProviderDialog
        key={addKey}
        available={available}
        open={addOpen}
        onOpenChange={setAddOpen}
        onAdd={add}
        isAdding={isAdding}
        addError={addError}
      />
      {keyTarget && (
        <ProviderKeyDialog
          key={keyDialogKey}
          connection={keyTarget}
          open={keyOpen}
          onOpenChange={setKeyOpen}
          onSave={(replacement) => save(keyTarget.slug, replacement)}
          isSaving={isReplacing}
          saveError={replaceError}
        />
      )}
      {modelsTarget && (
        <ProviderModelsDialog
          key={modelsDialogKey}
          connection={modelsTarget}
          open={modelsOpen}
          onOpenChange={setModelsOpen}
          onSaved={() => modelsSaved(modelsTarget)}
        />
      )}
      {deleting && (
        <ConfirmationDialog
          open={deleteOpen}
          onOpenChange={setDeleteOpen}
          variant="destructive"
          title={`Delete ${deleting.name}?`}
          description={
            BASE_URL_PROVIDER_TYPES.includes(deleting.providerType)
              ? `Its key is removed, and ${deleting.slug} can't be used again as a slug.`
              : `Its key is removed. You can add ${deleting.name} again later with a new key.`
          }
          confirmLabel="Delete provider"
          pendingLabel="Deleting…"
          isPending={isDeleting}
          onConfirm={() => confirmDelete(deleting).catch(() => undefined)}
        >
          {deleteError ? (
            <p className="mb-0 mt-3 text-[0.8rem]" style={{ color: "var(--err)" }} role="alert">
              {failureMessage(deleteError)}
            </p>
          ) : null}
        </ConfirmationDialog>
      )}
    </>
  );
}
