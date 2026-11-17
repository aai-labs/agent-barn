"use client";

import { useState } from "react";

import { ConfirmationDialog } from "@/components/confirmation-dialog";
import { ApiError } from "@/shared/api/error/errors";
import { getErrorDisplay } from "@/shared/api/error/get-error-display";
import { formatDate } from "@/shared/date";

import {
  BASE_URL_PROVIDER_TYPES,
  KNOWN_PROVIDER_TYPES,
  MASKED_KEY_PREFIX,
  PROVIDER_TYPE_LABELS,
} from "../constants";
import { useLlmProviderActions } from "../hooks/use-llm-provider-connections";
import type { LlmProviderConnection, NewLlmProviderConnection } from "../schemas";
import { AddLlmProviderDialog } from "./add-llm-provider-dialog";

export type Notice = { slug: string | null; text: string };

export function LlmProviderConnectionList({
  connections,
  notice,
  onNotice,
  onReplaceKey,
}: {
  connections: LlmProviderConnection[];
  notice: Notice | null;
  onNotice: (notice: Notice | null) => void;
  onReplaceKey: (connection: LlmProviderConnection) => void;
}) {
  const { addConnection, isAdding, addError, resetAdd, deleteConnection, isDeleting, deleteError, resetDelete } =
    useLlmProviderActions();
  const [addOpen, setAddOpen] = useState(false);
  const [addKey, setAddKey] = useState(0);
  const [deleting, setDeleting] = useState<LlmProviderConnection | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);

  const connected = new Set(connections.map((connection) => connection.providerType));
  const available = [...KNOWN_PROVIDER_TYPES.filter((type) => !connected.has(type)), ...BASE_URL_PROVIDER_TYPES];

  function openAdd() {
    resetAdd();
    onNotice(null);
    setAddKey((current) => current + 1);
    setAddOpen(true);
  }

  async function add(connection: NewLlmProviderConnection) {
    const saved = await addConnection(connection);
    setAddOpen(false);
    onNotice({ slug: null, text: `${saved.name} added.` });
  }

  function openDelete(connection: LlmProviderConnection) {
    resetDelete();
    onNotice(null);
    setDeleting(connection);
    setDeleteOpen(true);
  }

  async function confirmDelete(connection: LlmProviderConnection) {
    await deleteConnection(connection.slug);
    setDeleteOpen(false);
    onNotice({ slug: null, text: `${connection.name} deleted.` });
  }

  return (
    <section className="af-card overflow-hidden" aria-labelledby="other-providers-heading">
      <div className="p-5">
        <div className="flex items-start justify-between gap-4">
          <h3 id="other-providers-heading" className="m-0 text-sm font-medium">
            Other providers
          </h3>
          <button type="button" className="af-btn shrink-0" onClick={openAdd}>
            Add provider
          </button>
        </div>
        {connections.length === 0 ? (
          <p className="mb-0 mt-2 text-sm" style={{ color: "var(--ink-3)" }}>
            No other provider is connected.
          </p>
        ) : (
          <div className="mt-2">
            {connections.map((connection) => (
              <ConnectionCard
                key={connection.slug}
                connection={connection}
                notice={notice?.slug === connection.slug ? notice.text : null}
                onReplaceKey={() => onReplaceKey(connection)}
                onDelete={() => openDelete(connection)}
              />
            ))}
          </div>
        )}
        {notice && notice.slug === null && (
          <p role="status" className="mb-0 mt-4 text-sm">
            {notice.text}
          </p>
        )}
      </div>
      <AddLlmProviderDialog
        key={addKey}
        available={available}
        open={addOpen}
        onOpenChange={setAddOpen}
        onAdd={add}
        isAdding={isAdding}
        addError={addError}
      />
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
              {deleteFailure(deleteError)}
            </p>
          ) : null}
        </ConfirmationDialog>
      )}
    </section>
  );
}

function deleteFailure(error: unknown) {
  if (error instanceof ApiError && error.status === 404 && error.message) return error.message;
  return getErrorDisplay(error).description;
}

function ConnectionCard({
  connection,
  notice,
  onReplaceKey,
  onDelete,
}: {
  connection: LlmProviderConnection;
  notice: string | null;
  onReplaceKey: () => void;
  onDelete: () => void;
}) {
  const headingId = `llm-provider-${connection.slug}-heading`;
  const changed = connection.hasApiKey && connection.updatedAt ? formatDate(connection.updatedAt) : null;
  return (
    <section aria-labelledby={headingId} className="border-t py-3 first:border-t-0" style={{ borderColor: "var(--line)" }}>
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h4 id={headingId} className="m-0 text-sm font-medium">
            {connection.name}
          </h4>
          {connection.baseUrl && (
            <p className="mb-0 mt-1 text-sm break-all" style={{ color: "var(--ink-3)" }}>
              {PROVIDER_TYPE_LABELS[connection.providerType]} · {connection.baseUrl}
            </p>
          )}
          <p className="mb-0 mt-1 text-sm">
            {connection.hasApiKey ? `${MASKED_KEY_PREFIX}${connection.apiKeyLast4}` : "No key saved."}
          </p>
          {changed && (
            <p className="mb-0 mt-1 text-sm" style={{ color: "var(--ink-3)" }}>
              {connection.updatedBy ? `Changed by ${connection.updatedBy} on ${changed}` : `Changed on ${changed}`}
            </p>
          )}
        </div>
        <div className="flex shrink-0 gap-2">
          <button type="button" className="af-btn" onClick={onReplaceKey}>
            {connection.hasApiKey ? "Replace key" : "Save a key"}
          </button>
          <button type="button" className="af-btn" onClick={onDelete}>
            Delete
          </button>
        </div>
      </div>
      {notice && (
        <p role="status" className="mb-0 mt-2 text-sm">
          {notice}
        </p>
      )}
    </section>
  );
}
