"use client";

import { useState } from "react";
import { CheckIcon, XIcon } from "@/components/icons";
import {
  expandGithubContent,
  INTEGRATION_PROVIDERS,
  type IntegrationProvider,
} from "@/features/agents/integrations";
import { useActiveOrgRole } from "@/features/organizations/hooks/use-active-org-role";

import type { SharedCredentialRead } from "../schemas";
import {
  useCreateSharedCredential,
  useDeleteSharedCredential,
  useUpdateSharedCredential,
  useValidateSharedCredential,
} from "../hooks/use-shared-credential-mutations";
import {
  SHARED_CREDENTIAL_PROVIDER_LABELS,
  SHARED_CREDENTIAL_PROVIDERS,
} from "../utils";

type DrawerMode =
  | { kind: "create" }
  | { kind: "view"; credential: SharedCredentialRead };

interface SharedCredentialDrawerProps {
  mode: DrawerMode;
  onClose: () => void;
}

const ALLOWED_PROVIDER_IDS = new Set(
  Object.keys(SHARED_CREDENTIAL_PROVIDER_LABELS),
);

const MANUAL_PROVIDERS: IntegrationProvider[] = INTEGRATION_PROVIDERS.filter(
  (p) => ALLOWED_PROVIDER_IDS.has(p.id),
);

export function SharedCredentialDrawer({
  mode,
  onClose,
}: SharedCredentialDrawerProps) {
  const isCreate = mode.kind === "create";
  const credential = mode.kind === "view" ? mode.credential : null;
  const { canManage } = useActiveOrgRole();

  const [editing, setEditing] = useState(isCreate);
  const [confirming, setConfirming] = useState(false);

  const [provider, setProvider] = useState(credential?.provider ?? "");
  const [name, setName] = useState(credential?.name ?? "");
  const [content, setContent] = useState<Record<string, string | string[]>>({});

  const providerSpec = MANUAL_PROVIDERS.find((p) => p.id === provider);

  const createMutation = useCreateSharedCredential();
  const updateMutation = useUpdateSharedCredential();
  const deleteMutation = useDeleteSharedCredential();
  const validateMutation = useValidateSharedCredential();

  const isPending = createMutation.isPending || updateMutation.isPending;
  const mutationError = createMutation.error ?? updateMutation.error;

  function handleProviderChange(value: string) {
    setProvider(value);
    setContent({});
  }

  function setField(key: string, value: string | string[]) {
    setContent((prev) => ({ ...prev, [key]: value }));
  }

  function handleCancelEdit() {
    setEditing(false);
    setName(credential?.name ?? "");
    setProvider(credential?.provider ?? "");
    setContent({});
  }

  async function handleSave() {
    try {
      if (credential) {
        const payload: { credentialId: string; name?: string; content?: Record<string, string | string[]> } = {
          credentialId: credential.id,
        };
        const trimmedName = name.trim();
        if (trimmedName && trimmedName !== credential.name) {
          payload.name = trimmedName;
        }
        const hasContent = Object.values(content).some((v) =>
          Array.isArray(v) ? v.length > 0 : v.trim().length > 0,
        );
        if (hasContent) {
          payload.content = credential.provider === "github" ? expandGithubContent(content) : content;
        }
        await updateMutation.mutateAsync(payload);
        setEditing(false);
      } else {
        await createMutation.mutateAsync({
          provider,
          name: name.trim(),
          content: provider === "github" ? expandGithubContent(content) : content,
        });
        onClose();
      }
    } catch {
      // error displayed via mutationError
    }
  }

  async function handleDelete() {
    try {
      await deleteMutation.mutateAsync(credential!.id);
      onClose();
    } catch {
      // error displayed via deleteMutation.error
    }
  }

  async function handleValidate() {
    try {
      await validateMutation.mutateAsync(credential!.id);
    } catch {
      // error displayed via validateMutation.error
    }
  }

  const subLabel = isCreate
    ? "New credential"
    : editing
      ? "Edit credential"
      : "Credential";
  const heading = isCreate ? "New shared credential" : (credential?.name ?? "…");

  return (
    <div className="fixed inset-0 z-50">
      <div
        className="absolute inset-0"
        style={{ background: "rgba(20,16,10,.4)" }}
        onClick={onClose}
      />
      <aside
        className="absolute top-0 right-0 bottom-0 flex flex-col af-drawer-panel"
        style={{
          width: "min(36.25rem, 95vw)",
          background: "var(--bg)",
          boxShadow: "var(--shadow-pop)",
        }}
      >
        <header
          className="px-6 pt-5 pb-3.5 flex items-start justify-between"
          style={{ borderBottom: "1px solid var(--line)" }}
        >
          <div>
            <div
              className="text-xs uppercase tracking-[0.08em] font-semibold mb-1"
              style={{ color: "var(--ink-3)" }}
            >
              {subLabel}
            </div>
            <div className="flex items-center gap-2">
              <h2
                className="text-lg font-semibold tracking-tight m-0"
                style={{ color: "var(--ink)" }}
              >
                {heading}
              </h2>
              {credential && (
                <span
                  className="inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium"
                  style={{
                    background: "var(--bg-soft)",
                    color: "var(--ink-3)",
                    border: "1px solid var(--line)",
                  }}
                >
                  {SHARED_CREDENTIAL_PROVIDER_LABELS[credential.provider] ??
                    credential.provider}
                </span>
              )}
            </div>
          </div>
          <button
            className="af-btn af-btn-ghost af-btn-icon"
            onClick={onClose}
            aria-label="Close drawer"
          >
            <XIcon />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-6 py-5">
          {editing ? (
            <div className="flex flex-col gap-4">
              {credential && (
                <div
                  className="text-[0.8125rem] rounded-xl px-3.5 py-3 leading-[1.5]"
                  style={{
                    background: "var(--bg-soft)",
                    color: "var(--ink-3)",
                  }}
                >
                  Agents using this credential will pick up content changes on
                  their next start.
                </div>
              )}

              {isCreate && (
                <div className="flex flex-col gap-1.5">
                  <label
                    className="font-medium text-[0.844rem]"
                    style={{ color: "var(--ink)" }}
                  >
                    Provider <span style={{ color: "var(--err)" }}>*</span>
                  </label>
                  <select
                    className="af-select"
                    value={provider}
                    onChange={(e) => handleProviderChange(e.target.value)}
                  >
                    <option value="">Select a provider…</option>
                    {SHARED_CREDENTIAL_PROVIDERS.map((p) => (
                      <option key={p.value} value={p.value}>
                        {p.label}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              <div className="flex flex-col gap-1.5">
                <label
                  className="font-medium text-[0.844rem]"
                  style={{ color: "var(--ink)" }}
                >
                  Name <span style={{ color: "var(--err)" }}>*</span>
                </label>
                <input
                  className="af-input"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                  maxLength={255}
                  placeholder="e.g. Production Jira"
                />
              </div>

              {providerSpec && (
                <div className="flex flex-col gap-3">
                  {providerSpec.scopeNote && (
                    <div
                      className="text-[12px] leading-[1.5] rounded-lg px-3 py-2"
                      style={{
                        background: "var(--bg-soft)",
                        color: "var(--ink-4)",
                      }}
                    >
                      {providerSpec.scopeNote}
                    </div>
                  )}
                  {providerSpec.fields.map((field) => (
                    <div key={field.key} className="flex flex-col gap-1.5">
                      <label
                        className="font-medium text-[0.844rem]"
                        style={{ color: "var(--ink)" }}
                      >
                        {field.label}{" "}
                        {field.required && !credential && (
                          <span style={{ color: "var(--err)" }}>*</span>
                        )}
                      </label>
                      {field.type === "repo-list" ? (
                        <input
                          className="af-input"
                          placeholder={field.placeholder}
                          value={
                            Array.isArray(content[field.key])
                              ? (content[field.key] as string[]).join(", ")
                              : (content[field.key] as string) ?? ""
                          }
                          onChange={(e) => {
                            const val = e.target.value;
                            setField(
                              field.key,
                              val
                                ? val
                                    .split(",")
                                    .map((s) => s.trim())
                                    .filter(Boolean)
                                : [],
                            );
                          }}
                        />
                      ) : (
                        <input
                          className="af-input"
                          type={field.type === "secret" ? "password" : "text"}
                          placeholder={field.placeholder}
                          value={(content[field.key] as string) ?? ""}
                          onChange={(e) => setField(field.key, e.target.value)}
                        />
                      )}
                      {field.hint && (
                        <span
                          className="text-xs"
                          style={{ color: "var(--ink-4)" }}
                        >
                          {field.hint}
                        </span>
                      )}
                      {credential && field.type === "secret" && (
                        <span
                          className="text-xs"
                          style={{ color: "var(--ink-4)" }}
                        >
                          Leave empty to keep the current value.
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {mutationError && (
                <div
                  className="text-[0.8125rem]"
                  style={{ color: "var(--err)" }}
                >
                  {mutationError.message}
                </div>
              )}
            </div>
          ) : (
            <div className="flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <div
                  className="text-[13px] font-medium"
                  style={{ color: "var(--ink-2)" }}
                >
                  Name
                </div>
                <div className="text-[14px]" style={{ color: "var(--ink)" }}>
                  {credential?.name}
                </div>
              </div>
              <div className="flex flex-col gap-1.5">
                <div
                  className="text-[13px] font-medium"
                  style={{ color: "var(--ink-2)" }}
                >
                  Provider
                </div>
                <div className="text-[14px]" style={{ color: "var(--ink)" }}>
                  {SHARED_CREDENTIAL_PROVIDER_LABELS[
                    credential?.provider ?? ""
                  ] ?? credential?.provider}
                </div>
              </div>
              <div className="flex flex-col gap-1.5">
                <div
                  className="text-[13px] font-medium"
                  style={{ color: "var(--ink-2)" }}
                >
                  Used by
                </div>
                <div className="text-[14px]" style={{ color: "var(--ink)" }}>
                  {credential?.agentCount === 0
                    ? "No agents"
                    : credential?.agentCount === 1
                      ? "1 agent"
                      : `${credential?.agentCount} agents`}
                </div>
              </div>

              {validateMutation.isSuccess && (
                <div
                  className="flex items-center gap-2 text-[0.8125rem] rounded-xl px-3.5 py-3"
                  style={{ background: "var(--bg-soft)", color: "var(--ok)" }}
                >
                  <CheckIcon size={14} /> Credential validated successfully.
                </div>
              )}
              {validateMutation.error && (
                <div
                  className="text-[0.8125rem] rounded-xl px-3.5 py-3"
                  style={{ background: "var(--bg-soft)", color: "var(--err)" }}
                >
                  Validation failed: {validateMutation.error.message}
                </div>
              )}
            </div>
          )}
        </div>

        <footer
          className="px-6 py-4 flex items-center gap-2 flex-shrink-0"
          style={{ borderTop: "1px solid var(--line)" }}
        >
          {editing ? (
            <>
              <button
                type="button"
                className="af-btn af-btn-ghost"
                onClick={isCreate ? onClose : handleCancelEdit}
              >
                Cancel
              </button>
              <button
                type="button"
                className="af-btn af-btn-primary ml-auto"
                disabled={isPending || !provider || !name.trim()}
                onClick={() => {
                  void handleSave();
                }}
              >
                {isPending
                  ? "Saving…"
                  : isCreate
                    ? "Create credential"
                    : "Save changes"}
              </button>
            </>
          ) : confirming ? (
            <div className="flex flex-col gap-2 w-full">
              <div className="flex items-center gap-2">
                <span
                  className="text-[13px] flex-1"
                  style={{ color: "var(--ink-3)" }}
                >
                  {(credential?.agentCount ?? 0) > 0 ? (
                    <>
                      Cannot delete{" "}
                      <strong style={{ color: "var(--ink)" }}>
                        {credential?.name}
                      </strong>{" "}
                      — it is attached to{" "}
                      {credential?.agentCount === 1
                        ? "1 agent"
                        : `${credential?.agentCount} agents`}
                      . Detach it first.
                    </>
                  ) : (
                    <>
                      Delete{" "}
                      <strong style={{ color: "var(--ink)" }}>
                        {credential?.name}
                      </strong>
                      ? This cannot be undone.
                    </>
                  )}
                </span>
                <button
                  type="button"
                  className="af-btn af-btn-ghost af-btn-sm"
                  disabled={deleteMutation.isPending}
                  onClick={() => {
                    setConfirming(false);
                    deleteMutation.reset();
                  }}
                >
                  Cancel
                </button>
                {(credential?.agentCount ?? 0) === 0 && (
                  <button
                    type="button"
                    className="af-btn af-btn-sm"
                    style={{
                      borderColor: "var(--err)",
                      color: "var(--err)",
                    }}
                    disabled={deleteMutation.isPending}
                    onClick={() => {
                      void handleDelete();
                    }}
                  >
                    {deleteMutation.isPending ? "Deleting…" : "Delete"}
                  </button>
                )}
              </div>
              {deleteMutation.error && (
                <div
                  className="text-[0.8125rem]"
                  style={{ color: "var(--err)" }}
                >
                  {deleteMutation.error.message}
                </div>
              )}
            </div>
          ) : (
            <>
              {canManage && (
                <>
                  <button
                    className="af-btn af-btn-ghost af-btn-sm"
                    style={{ color: "var(--err)" }}
                    onClick={() => setConfirming(true)}
                  >
                    Delete
                  </button>
                  <button
                    className="af-btn af-btn-ghost af-btn-sm"
                    disabled={validateMutation.isPending}
                    onClick={() => {
                      void handleValidate();
                    }}
                  >
                    {validateMutation.isPending ? "Validating…" : "Validate"}
                  </button>
                  <button
                    className="af-btn af-btn-primary ml-auto"
                    onClick={() => setEditing(true)}
                  >
                    Edit credential
                  </button>
                </>
              )}
              {!canManage && (
                <button
                  className="af-btn af-btn-ghost ml-auto"
                  onClick={onClose}
                >
                  Close
                </button>
              )}
            </>
          )}
        </footer>
      </aside>
    </div>
  );
}
