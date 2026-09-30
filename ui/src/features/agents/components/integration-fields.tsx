"use client";

import { useState } from "react";

import type { GoogleOAuthResult } from "../hooks/use-google-oauth";
import { isOAuthConnected, type IntegrationDraft, type IntegrationProvider } from "../integrations";
import { CredentialErrorAlert } from "./credential-error-alert";
import { FormField, GoogleAuthButton, RepoListField, TokenInput } from "./hire-dialog-primitives";

/**
 * Renders one provider's credential inputs: the OAuth button for OAuth-based
 * providers, otherwise a field per `provider.fields` (repo-list / secret / radio /
 * plain text). Shared by every surface that collects integration credentials —
 * the hire dialog's skills and integrations steps, the agent skills tab, and the
 * config drawer's re-pin flow.
 *
 * The surfaces differ only in presentation, so those differences are props rather
 * than forks: `namePrefix` keeps each surface's radio groups in their own DOM
 * namespace (same `name` across two mounted surfaces would make them interfere),
 * `showScopeNote` reflects that only the hire steps render scope guidance, and
 * `disabled` is used by the config drawer to lock inputs while an agent runs.
 */
export function IntegrationFields({
  provider,
  draft,
  onFieldChange,
  onListChange,
  onOAuthConnected,
  namePrefix = "",
  showScopeNote = false,
  credentialError,
  disabled,
}: {
  provider: IntegrationProvider;
  draft: IntegrationDraft;
  onFieldChange: (key: string, value: string) => void;
  onListChange: (key: string, values: string[]) => void;
  onOAuthConnected?: (result: GoogleOAuthResult) => void;
  namePrefix?: string;
  showScopeNote?: boolean;
  credentialError?: string | null;
  disabled?: boolean;
}) {
  const [visible, setVisible] = useState<Record<string, boolean>>({});

  // Scopes are derived from these fields at consent time, so they must be filled in
  // before the popup opens — hence fields render above the button, and the button is
  // held back until the required ones are set.
  const services = Array.isArray(draft.content.services) ? (draft.content.services as string[]) : [];
  const needsServices = provider.fields.some((f) => f.key === "services" && f.required);
  const hasReadOnly = draft.content.readOnly === "true" || draft.content.readOnly === "false";
  const connected = isOAuthConnected(draft);
  const connectedEmail = typeof draft.content.email === "string" ? draft.content.email.trim() : "";
  const fieldsDisabled = disabled || (provider.authMethod === "google_oauth" && connected);
  const authorizeParams = needsServices
    ? { services: services.join(","), read_only: draft.content.readOnly === "true" ? "true" : "false" }
    : undefined;

  const renderedFields = provider.fields.map((field) => {
    if (field.dependsOn && draft.content[field.dependsOn.key] !== field.dependsOn.value) {
      return null;
    }
    const label = field.required ? field.label : `${field.label} (optional)`;

    if (field.type === "repo-list") {
      const repos = Array.isArray(draft.content[field.key])
        ? (draft.content[field.key] as string[])
        : [];
      return (
        <FormField key={field.key} label={label} hint={field.hint}>
          <RepoListField
            repos={repos}
            onChange={(next) => onListChange(field.key, next)}
            placeholder={field.placeholder}
          />
        </FormField>
      );
    }

    if (field.type === "checkbox-list") {
      const selected = Array.isArray(draft.content[field.key])
        ? (draft.content[field.key] as string[])
        : [];
      return (
        <FormField key={field.key} label={label} hint={field.hint}>
          <div className="flex flex-col gap-2 mt-1">
            {field.options?.map((opt) => (
              <label key={opt.value} className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={selected.includes(opt.value)}
                  onChange={(e) =>
                    onListChange(
                      field.key,
                      e.target.checked
                        ? [...selected, opt.value]
                        : selected.filter((v) => v !== opt.value),
                    )
                  }
                  disabled={fieldsDisabled}
                  className="accent-[var(--blue-9)]"
                />
                <span className="text-[13px]" style={{ color: "var(--ink-1)" }}>{opt.label}</span>
              </label>
            ))}
          </div>
        </FormField>
      );
    }

    const rawValue = draft.content[field.key];
    const value = typeof rawValue === "string" ? rawValue : "";

    if (field.type === "secret") {
      return (
        <FormField key={field.key} label={label} hint={field.hint}>
          <TokenInput
            value={value}
            onChange={(v) => onFieldChange(field.key, v)}
            visible={!!visible[field.key]}
            onToggle={() => setVisible((s) => ({ ...s, [field.key]: !s[field.key] }))}
            placeholder={field.placeholder}
            disabled={fieldsDisabled}
          />
        </FormField>
      );
    }

    if (field.type === "radio") {
      return (
        <FormField key={field.key} label={label} hint={field.hint}>
          <div className="flex flex-col gap-2 mt-1">
            {field.options?.map((opt) => (
              <label key={opt.value} className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  name={`${namePrefix}${provider.id}-${field.key}`}
                  value={opt.value}
                  checked={value === opt.value}
                  onChange={(e) => onFieldChange(field.key, e.target.value)}
                  disabled={fieldsDisabled}
                  className="accent-[var(--blue-9)]"
                />
                <span className="text-[13px]" style={{ color: "var(--ink-1)" }}>{opt.label}</span>
              </label>
            ))}
          </div>
        </FormField>
      );
    }

    return (
      <FormField key={field.key} label={label} hint={field.hint}>
        <input
          className="af-input"
          value={value}
          onChange={(e) => onFieldChange(field.key, e.target.value)}
          placeholder={field.placeholder}
          autoComplete="off"
          disabled={fieldsDisabled}
        />
      </FormField>
    );
  });

  return (
    <>
      {showScopeNote && provider.scopeNote && (
        <p className="text-[0.75rem] leading-[1.4]" style={{ color: "var(--ink-3)" }}>
          {provider.scopeNote}
        </p>
      )}

      {credentialError && <CredentialErrorAlert message={credentialError} />}

      {renderedFields}

      {provider.authMethod === "google_oauth" && onOAuthConnected && (
        <GoogleAuthButton
          connected={connected}
          onConnected={onOAuthConnected}
          disabled={disabled || (needsServices && (services.length === 0 || !hasReadOnly))}
          disabledNote={
            needsServices && services.length === 0
              ? "Pick at least one service before connecting."
              : needsServices && !hasReadOnly
                ? "Choose an access level before connecting."
                : undefined
          }
          provider={provider.id}
          connectedNote={provider.oauthConnectedNote}
          connectedEmail={connectedEmail || undefined}
          authorizeParams={authorizeParams}
          requireEmail={needsServices}
        />
      )}
    </>
  );
}
