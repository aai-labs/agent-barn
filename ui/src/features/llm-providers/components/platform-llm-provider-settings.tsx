"use client";

import { useState } from "react";
import { toast } from "sonner";

import { AppErrorState } from "@/components/app-error-state";
import { ConfirmationDialog } from "@/components/confirmation-dialog";

import { BASE_URL_PROVIDER_TYPES, KNOWN_PROVIDER_TYPES } from "../constants";
import { useLlmProviderActions, useLlmProviderConnections } from "../hooks/use-llm-provider-connections";
import type { KeyReplacement, LlmProviderConnection, NewLlmProviderConnection, ProviderType } from "../schemas";
import { failureMessage, providerTitle } from "../utils";
import { AddLlmProviderDialog } from "./add-llm-provider-dialog";
import { DeploymentProviderCard } from "./deployment-provider-card";
import { ManageProviderMenu } from "./manage-provider-menu";
import { AddProviderCard, ProviderCard } from "./provider-card";
import { ProviderKeyDialog } from "./provider-key-dialog";
import { ProviderModelsDialog } from "./provider-models-dialog";
import { ProviderOrganizationsDialog } from "./provider-organizations-dialog";

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
  const [addType, setAddType] = useState<ProviderType | null>(null);
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
  const [organizationsTarget, setOrganizationsTarget] = useState<LlmProviderConnection | null>(null);
  const [organizationsOpen, setOrganizationsOpen] = useState(false);
  const [organizationsDialogKey, setOrganizationsDialogKey] = useState(0);
  const [menuTrigger, setMenuTrigger] = useState<HTMLElement | null>(null);

  if (isLoadingConnections) return <p role="status">Loading LLM provider settings…</p>;
  if (connectionsError || !connections)
    return (
      <AppErrorState
        error={connectionsError}
        title="Could not load LLM provider settings"
        onRetry={() => void reloadConnections()}
      />
    );

  const ofType = (type: ProviderType) => connections.filter((connection) => connection.providerType === type);
  const openRouter = ofType("openrouter")[0];
  const deployment = openRouter?.envKeyConfigured ? openRouter : undefined;
  const gridOpenRouter = deployment ? undefined : openRouter;
  const countedTypes: LlmProviderConnection[][] = [
    ...(gridOpenRouter ? [[gridOpenRouter]] : []),
    ...KNOWN_PROVIDER_TYPES.map(ofType),
    ofType("azure"),
  ];
  const connectedCount = countedTypes.filter((group) => group.some((connection) => connection.hasApiKey)).length;

  function openAdd(type: ProviderType) {
    resetAdd();
    setAddType(type);
    setAddKey((current) => current + 1);
    setAddOpen(true);
  }

  async function add(connection: NewLlmProviderConnection) {
    const saved = await addConnection(connection);
    setAddOpen(false);
    toast.success(`${providerTitle(saved)} added`);
  }

  function openKeyDialog(connection: LlmProviderConnection, trigger: HTMLElement | null) {
    setMenuTrigger(trigger);
    resetReplace();
    setKeyTarget(connection);
    setKeyDialogKey((current) => current + 1);
    setKeyOpen(true);
  }

  async function save(slug: string, replacement: KeyReplacement) {
    const saved = await replaceKey({ slug, ...replacement });
    setKeyOpen(false);
    toast.success(`${providerTitle(saved)} key saved`);
  }

  function openModels(connection: LlmProviderConnection, trigger: HTMLElement | null) {
    setMenuTrigger(trigger);
    setModelsTarget(connection);
    setModelsDialogKey((current) => current + 1);
    setModelsOpen(true);
  }

  function modelsSaved(connection: LlmProviderConnection) {
    setModelsOpen(false);
    toast.success(`${providerTitle(connection)} models saved`);
  }

  function openOrganizations(connection: LlmProviderConnection, trigger: HTMLElement | null) {
    setMenuTrigger(trigger);
    setOrganizationsTarget(connection);
    setOrganizationsDialogKey((current) => current + 1);
    setOrganizationsOpen(true);
  }

  function organizationsSaved(connection: LlmProviderConnection) {
    setOrganizationsOpen(false);
    toast.success(`${providerTitle(connection)} organizations saved`);
  }

  function openDelete(connection: LlmProviderConnection) {
    resetDelete();
    setDeleting(connection);
    setDeleteOpen(true);
  }

  async function confirmDelete(connection: LlmProviderConnection) {
    await deleteConnection(connection.slug);
    setDeleteOpen(false);
    toast.success(`${providerTitle(connection)} deleted`);
  }

  function manageMenu(connection: LlmProviderConnection) {
    const isOpenRouter = connection.providerType === "openrouter";
    return (
      <ManageProviderMenu
        connection={connection}
        onModels={isOpenRouter ? undefined : (trigger) => openModels(connection, trigger)}
        onOrganizations={(trigger) => openOrganizations(connection, trigger)}
        onReplaceKey={(trigger) => openKeyDialog(connection, trigger)}
        onDelete={isOpenRouter ? undefined : () => openDelete(connection)}
      />
    );
  }

  function connectionCard(connection: LlmProviderConnection) {
    return (
      <li key={connection.slug}>
        <ProviderCard connection={connection} manage={manageMenu(connection)} />
      </li>
    );
  }

  return (
    <>
      {deployment && (
        <section aria-labelledby="llm-providers-deployment-heading" className="mb-6">
          <h2 id="llm-providers-deployment-heading" className="mb-3 mt-0 text-[0.95rem] font-semibold">
            Set by this deployment
          </h2>
          <DeploymentProviderCard connection={deployment} manage={manageMenu(deployment)} />
        </section>
      )}

      <section aria-labelledby="llm-providers-grid-heading">
        <h2 id="llm-providers-grid-heading" className="mb-1 mt-0 text-[0.95rem] font-semibold">
          Providers · {connectedCount} of {countedTypes.length} connected
        </h2>
        <p className="mb-3 mt-0 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
          Each key is checked with its provider before it is saved, and only its last four characters are shown.
        </p>
        <ul aria-label="LLM providers" className="m-0 grid list-none auto-rows-fr grid-cols-1 gap-3 p-0 md:grid-cols-3">
          {gridOpenRouter && connectionCard(gridOpenRouter)}
          {KNOWN_PROVIDER_TYPES.map((type) => {
            const connection = ofType(type)[0];
            if (connection) return connectionCard(connection);
            return (
              <li key={type}>
                <AddProviderCard providerType={type} actionLabel="Add key" showStatus onAdd={() => openAdd(type)} />
              </li>
            );
          })}
          {BASE_URL_PROVIDER_TYPES.flatMap(ofType).map(connectionCard)}
          <li>
            <AddProviderCard providerType="azure" actionLabel="Add key" onAdd={() => openAdd("azure")} />
          </li>
          <li>
            <AddProviderCard providerType="custom" actionLabel="Add endpoint" dashed onAdd={() => openAdd("custom")} />
          </li>
        </ul>
      </section>

      {addType && (
        <AddLlmProviderDialog
          key={`add-${addKey}`}
          providerType={addType}
          open={addOpen}
          onOpenChange={setAddOpen}
          onAdd={add}
          isAdding={isAdding}
          addError={addError}
        />
      )}
      {keyTarget && (
        <ProviderKeyDialog
          key={`key-${keyDialogKey}`}
          connection={keyTarget}
          open={keyOpen}
          onOpenChange={setKeyOpen}
          onSave={(replacement) => save(keyTarget.slug, replacement)}
          isSaving={isReplacing}
          saveError={replaceError}
          returnFocusTo={menuTrigger}
        />
      )}
      {modelsTarget && (
        <ProviderModelsDialog
          key={`models-${modelsDialogKey}`}
          connection={modelsTarget}
          open={modelsOpen}
          onOpenChange={setModelsOpen}
          onSaved={() => modelsSaved(modelsTarget)}
          returnFocusTo={menuTrigger}
        />
      )}
      {organizationsTarget && (
        <ProviderOrganizationsDialog
          key={`organizations-${organizationsDialogKey}`}
          connection={organizationsTarget}
          open={organizationsOpen}
          onOpenChange={setOrganizationsOpen}
          onSaved={() => organizationsSaved(organizationsTarget)}
          returnFocusTo={menuTrigger}
        />
      )}
      {deleting && (
        <ConfirmationDialog
          open={deleteOpen}
          onOpenChange={setDeleteOpen}
          variant="destructive"
          title={`Delete ${providerTitle(deleting)}?`}
          description={
            BASE_URL_PROVIDER_TYPES.includes(deleting.providerType)
              ? `Its key and models are removed, and ${deleting.slug} can't be used again as a slug.`
              : `Its key and models are removed. You can add ${providerTitle(deleting)} again later with a new key.`
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
