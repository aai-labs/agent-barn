"use client";

import { useState } from "react";

import type { GoogleOAuthResult } from "../hooks/use-google-oauth";
import { isOAuthConnected, type IntegrationDraft, type IntegrationProvider } from "../integrations";
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
  onReposChange,
  onOAuthConnected,
  namePrefix = "",
  showScopeNote = false,
  disabled,
}: {
  provider: IntegrationProvider;
  draft: IntegrationDraft;
  onFieldChange: (key: string, value: string) => void;
  onReposChange: (key: string, repos: string[]) => void;
  onOAuthConnected?: (result: GoogleOAuthResult) => void;
  namePrefix?: string;
  showScopeNote?: boolean;
  disabled?: boolean;
}) {
  const [visible, setVisible] = useState<Record<string, boolean>>({});

  return (
    <>
      {showScopeNote && provider.scopeNote && (
        <p className="text-[0.75rem] leading-[1.4]" style={{ color: "var(--ink-3)" }}>
          {provider.scopeNote}
        </p>
      )}

      {provider.authMethod === "google_oauth" && onOAuthConnected && (
        <GoogleAuthButton
          connected={isOAuthConnected(draft)}
          onConnected={onOAuthConnected}
          disabled={disabled}
          provider={provider.id}
          connectedNote={provider.oauthConnectedNote}
        />
      )}

      {provider.fields.map((field) => {
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
                onChange={(next) => onReposChange(field.key, next)}
                placeholder={field.placeholder}
              />
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
                disabled={disabled}
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
                      disabled={disabled}
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
              disabled={disabled}
            />
          </FormField>
        );
      })}
    </>
  );
}
