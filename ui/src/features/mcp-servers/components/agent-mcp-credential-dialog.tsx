"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

import type { AgentMcpCredentialWrite, AgentMcpServer, McpAuthType, McpStaticAuthType } from "../schemas";
import { type HeaderDraft, McpCredentialFields, headersPayload } from "./mcp-credential-fields";
import { McpNotice, McpServerIcon } from "./mcp-ui";

/**
 * An Agent's own token and headers for a token-based MCP server. The gateway uses it instead
 * of the organization's credential; whether the Agent has the server at all is unchanged.
 */
export function AgentMcpCredentialDialog({
  server,
  open,
  onOpenChange,
  onSave,
  isSaving,
  error,
}: {
  server: AgentMcpServer;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (data: AgentMcpCredentialWrite) => Promise<unknown>;
  isSaving: boolean;
  error: unknown;
}) {
  // Prefilled from the Agent's saved credential; its token and secret header values are never
  // read back, and leaving them blank keeps the saved ones under the same scheme and name.
  const saved = server.agentCredential ?? null;
  const initialType: McpStaticAuthType =
    saved?.authType ?? (server.authType === "oauth" ? "bearer" : (server.authType as McpStaticAuthType));
  const [authType, setAuthType] = useState<McpStaticAuthType>(initialType);
  const [headerName, setHeaderName] = useState(saved?.authHeaderName ?? "");
  const [token, setToken] = useState("");
  const [headers, setHeaders] = useState<HeaderDraft[]>(
    (saved?.headers ?? []).map((header) => ({
      name: header.name,
      value: header.value ?? "",
      secret: header.secret,
    })),
  );
  const tokenSaved =
    saved !== null &&
    saved.authType === authType &&
    (authType !== "api_key" || (saved.authHeaderName ?? "").toLowerCase() === headerName.trim().toLowerCase());
  const savedSecret = (name: string) =>
    saved?.headers.some((header) => header.secret && header.name.toLowerCase() === name.toLowerCase()) ?? false;

  const canSubmit =
    (authType !== "api_key" || headerName.trim() !== "") &&
    (authType === "none" || token !== "" || tokenSaved) &&
    headers.every(
      (header) => header.name.trim() !== "" && (!header.secret || header.value || savedSecret(header.name)),
    );

  async function submit() {
    const auth: AgentMcpCredentialWrite["auth"] = { type: authType };
    if (authType === "api_key") auth.headerName = headerName.trim();
    if (authType !== "none" && token) auth.token = token;
    try {
      await onSave({ auth, headers: headersPayload(headers) });
      onOpenChange(false);
    } catch {
      // Shown inline from `error`.
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[90vh] flex-col gap-0 p-0 sm:max-w-[38rem]">
        <DialogHeader className="border-b px-6 pt-5 pb-4" style={{ borderColor: "var(--line)" }}>
          <div className="flex items-center gap-3">
            <McpServerIcon />
            <div className="min-w-0">
              <DialogTitle>This Agent&apos;s own credential for {server.name}</DialogTitle>
              <DialogDescription className="mt-0.5">
                The Agent reaches {server.name} with this instead of the organization&apos;s credential. It never enters
                the Agent: the credential gateway adds it. Saving checks it against the server.
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>
        <div className="flex flex-1 flex-col gap-3.5 overflow-y-auto px-6 py-5">
          <McpCredentialFields
            idPrefix="agent-mcp"
            authType={authType}
            onAuthTypeChange={(type: McpAuthType) => setAuthType(type as McpStaticAuthType)}
            allowOAuth={false}
            headerName={headerName}
            onHeaderNameChange={setHeaderName}
            token={token}
            onTokenChange={setToken}
            tokenSaved={tokenSaved}
            headers={headers}
            onHeadersChange={setHeaders}
            savedSecret={savedSecret}
          />
          {Boolean(error) && (
            <McpNotice tone="error" title="Could not save the credential">
              {error instanceof Error ? error.message : "Something went wrong"}
            </McpNotice>
          )}
        </div>
        <DialogFooter className="border-t px-6 py-4" style={{ borderColor: "var(--line)" }}>
          <button type="button" className="af-btn af-btn-ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </button>
          <button
            type="button"
            className="af-btn af-btn-primary"
            disabled={!canSubmit || isSaving}
            onClick={() => void submit()}
          >
            {isSaving && <Loader2 size={14} className="animate-spin" />}
            {isSaving ? "Checking and saving…" : "Save credential"}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
