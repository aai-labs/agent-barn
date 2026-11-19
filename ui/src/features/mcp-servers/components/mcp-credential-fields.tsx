"use client";

import { Plus, Trash2 } from "lucide-react";

import { Checkbox } from "@/components/ui/checkbox";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

import type { McpAuthType } from "../schemas";
import { McpField } from "./mcp-ui";

export type HeaderDraft = { name: string; value: string; secret: boolean };

const SAVED = "Saved — leave blank to keep it";

/**
 * Authentication and extra headers for an MCP server credential: the organization's, on the
 * server dialog, or an Agent's own. Secret values are never shown back; a saved one is kept
 * when its field is left blank.
 */
export function McpCredentialFields({
  idPrefix,
  authType,
  onAuthTypeChange,
  allowOAuth,
  headerName,
  onHeaderNameChange,
  token,
  onTokenChange,
  tokenSaved,
  headers,
  onHeadersChange,
  savedSecret,
}: {
  idPrefix: string;
  authType: McpAuthType;
  onAuthTypeChange: (type: McpAuthType) => void;
  allowOAuth: boolean;
  headerName: string;
  onHeaderNameChange: (value: string) => void;
  token: string;
  onTokenChange: (value: string) => void;
  tokenSaved: boolean;
  headers: HeaderDraft[];
  onHeadersChange: (headers: HeaderDraft[]) => void;
  savedSecret: (headerName: string) => boolean;
}) {
  const update = (index: number, change: Partial<HeaderDraft>) =>
    onHeadersChange(headers.map((header, i) => (i === index ? { ...header, ...change } : header)));

  return (
    <>
      <div className="grid gap-3.5 sm:grid-cols-2">
        <McpField id={`${idPrefix}-auth`} label="Authentication">
          <Select value={authType} onValueChange={(value) => onAuthTypeChange(value as McpAuthType)}>
            <SelectTrigger id={`${idPrefix}-auth`} aria-label="Authentication" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectItem value="none">No authentication</SelectItem>
                <SelectItem value="bearer">Bearer token</SelectItem>
                <SelectItem value="api_key">API key header</SelectItem>
                {allowOAuth && <SelectItem value="oauth">OAuth sign-in</SelectItem>}
              </SelectGroup>
            </SelectContent>
          </Select>
        </McpField>
        {authType === "api_key" && (
          <McpField id={`${idPrefix}-header-name`} label="Header name">
            <input
              id={`${idPrefix}-header-name`}
              className="af-input w-full font-mono text-[0.8rem]"
              value={headerName}
              maxLength={128}
              placeholder="X-API-Key"
              autoComplete="off"
              onChange={(e) => onHeaderNameChange(e.target.value)}
            />
          </McpField>
        )}
      </div>
      {(authType === "bearer" || authType === "api_key") && (
        <McpField id={`${idPrefix}-token`} label={authType === "bearer" ? "Token" : "API key"}>
          <input
            id={`${idPrefix}-token`}
            type="password"
            autoComplete="off"
            className="af-input w-full"
            value={token}
            maxLength={8192}
            placeholder={tokenSaved ? SAVED : ""}
            onChange={(e) => onTokenChange(e.target.value)}
          />
        </McpField>
      )}

      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between gap-2">
          <span className="text-[0.8rem] font-medium text-[var(--ink-2)]">Additional headers</span>
          <button
            type="button"
            className="af-btn af-btn-sm af-btn-ghost"
            disabled={headers.length >= 32}
            onClick={() => onHeadersChange([...headers, { name: "", value: "", secret: false }])}
          >
            <Plus size={13} /> Add header
          </button>
        </div>
        {headers.length === 0 && (
          <p className="m-0 text-[0.76rem] text-[var(--ink-4)]">
            None. Add one for servers that need more than a token.
          </p>
        )}
        {headers.map((header, index) => (
          <div
            key={index}
            className="flex flex-wrap items-end gap-2 rounded-xl border p-3"
            style={{ borderColor: "var(--line)" }}
          >
            <div className="min-w-36 flex-1">
              <McpField id={`${idPrefix}-header-${index}-name`} label="Header name">
                <input
                  id={`${idPrefix}-header-${index}-name`}
                  className="af-input w-full font-mono text-[0.8rem]"
                  value={header.name}
                  maxLength={128}
                  autoComplete="off"
                  onChange={(e) => update(index, { name: e.target.value })}
                />
              </McpField>
            </div>
            <div className="min-w-36 flex-1">
              <McpField id={`${idPrefix}-header-${index}-value`} label="Header value">
                <input
                  id={`${idPrefix}-header-${index}-value`}
                  type={header.secret ? "password" : "text"}
                  autoComplete="off"
                  className="af-input w-full"
                  value={header.value}
                  maxLength={8192}
                  placeholder={header.secret && savedSecret(header.name) ? SAVED : ""}
                  onChange={(e) => update(index, { value: e.target.value })}
                />
              </McpField>
            </div>
            <label
              htmlFor={`${idPrefix}-header-${index}-secret`}
              className="flex items-center gap-2 pb-2.5 text-[0.8rem] text-[var(--ink-2)]"
            >
              <Checkbox
                id={`${idPrefix}-header-${index}-secret`}
                checked={header.secret}
                onCheckedChange={(checked) => update(index, { secret: checked === true })}
              />
              Secret
            </label>
            <button
              type="button"
              className="af-btn af-btn-ghost af-btn-icon mb-0.5"
              aria-label={`Remove header ${index + 1}`}
              title="Remove header"
              onClick={() => onHeadersChange(headers.filter((_, i) => i !== index))}
            >
              <Trash2 size={14} />
            </button>
          </div>
        ))}
      </div>
    </>
  );
}

/** The headers as an API write: a secret left blank is sent without a value, keeping the saved one. */
export function headersPayload(headers: HeaderDraft[]): { name: string; value?: string; secret: boolean }[] {
  return headers.map((header) =>
    header.secret && !header.value
      ? { name: header.name.trim(), secret: true }
      : {
          name: header.name.trim(),
          value: header.value,
          secret: header.secret,
        },
  );
}
