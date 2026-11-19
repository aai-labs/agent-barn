"use client";

import { useState } from "react";
import { Loader2, PlugZap } from "lucide-react";

import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

import { useProbeMcpServer, useSaveMcpServer } from "../hooks/use-mcp-servers";
import { type HeaderDraft, McpCredentialFields, headersPayload } from "./mcp-credential-fields";
import { McpField, McpFieldGroup, McpNotice, McpServerIcon, McpSwitch } from "./mcp-ui";
import type { McpAuthType, McpServer, McpServerProbe, McpServerScope, McpServerWrite } from "../schemas";
import { identifierFromName } from "../utils";

// Recomputed here from the current checkboxes, so the probe's own version of these is dropped.
const FILTER_DEPENDENT_WARNINGS = ["Several tools would share", "No tools are visible", "The tool filter names"];

function errorMessage(error: unknown): string | null {
  if (!error) return null;
  return error instanceof Error ? error.message : "Something went wrong";
}

/**
 * Add or edit an Organization MCP Server or, with `agentId`, one of that Agent's own. Saving
 * connects to the server once, so "Test connection" shows the same answer ahead of time and
 * lets whoever manages it choose which of its tools Agents see.
 */
export function McpServerDialog({
  server,
  agentId,
  open,
  onOpenChange,
}: {
  server: McpServer | null;
  /** An Agent MCP Server of this Agent: no scope, never restricted. */
  agentId?: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const forAgent = Boolean(agentId);
  const [name, setName] = useState(server?.name ?? "");
  const [url, setUrl] = useState(server?.url ?? "");
  const [description, setDescription] = useState(server?.description ?? "");
  const [authType, setAuthType] = useState<McpAuthType>(server?.authType ?? "none");
  const [headerName, setHeaderName] = useState(server?.authHeaderName ?? "");
  const [token, setToken] = useState("");
  const ownAppSaved = server?.authType === "oauth" && server.oauthRegistered === false;
  const [ownApp, setOwnApp] = useState(ownAppSaved);
  const [clientId, setClientId] = useState(ownAppSaved ? (server?.oauthClientId ?? "") : "");
  const [clientSecret, setClientSecret] = useState("");
  const [oauthScope, setOauthScope] = useState("");
  const [headers, setHeaders] = useState<HeaderDraft[]>(
    (server?.headers ?? []).map((header) => ({
      name: header.name,
      value: header.value ?? "",
      secret: header.secret,
    })),
  );
  const [scope, setScope] = useState<Exclude<McpServerScope, "agent">>(
    server?.scope === "all_agents" ? "all_agents" : "selected_agents",
  );
  const [restricted, setRestricted] = useState(server?.restricted ?? false);
  const [enabled, setEnabled] = useState(server?.enabled ?? true);
  const [probe, setProbe] = useState<McpServerProbe | null>(null);
  const [visible, setVisible] = useState<Record<string, boolean>>({});
  const [hideNewTools, setHideNewTools] = useState(server?.toolInclude != null);
  const [filterTouched, setFilterTouched] = useState(false);

  const save = useSaveMcpServer(agentId);
  const test = useProbeMcpServer(agentId);

  const identifier = server?.identifier ?? identifierFromName(name);
  // A saved token is kept when the same scheme is sent in the same header without one.
  const tokenSaved =
    !!server &&
    server.authType === authType &&
    (authType !== "api_key" || (server.authHeaderName ?? "").toLowerCase() === headerName.trim().toLowerCase());
  const savedSecret = (headerName: string) =>
    server?.headers.some((saved) => saved.secret && saved.name.toLowerCase() === headerName.toLowerCase()) ?? false;

  const shownTools =
    probe?.tools.map((tool) => ({
      ...tool,
      visible: visible[tool.name] ?? tool.visible,
    })) ?? [];
  const visibleTools = shownTools.filter((tool) => tool.visible);
  const openclawCounts = new Map<string, number>();
  for (const tool of visibleTools)
    openclawCounts.set(tool.openclawName, (openclawCounts.get(tool.openclawName) ?? 0) + 1);
  const collisions = [...openclawCounts].filter(([, count]) => count > 1).map(([openclawName]) => openclawName);

  const oauth = authType === "oauth";
  // An OAuth server is tested with its sign-in (the organization's, or for an Agent server the
  // Agent's), so only once it is signed in.
  const canTest = !oauth || server?.signIn?.status === "signed_in";
  const redirectUri =
    typeof window === "undefined"
      ? "/api/v1/mcp-servers/oauth/callback"
      : `${window.location.origin}/api/v1/mcp-servers/oauth/callback`;
  const missingToken = (authType === "bearer" || authType === "api_key") && !token && !tokenSaved;
  const canSubmit =
    name.trim() !== "" &&
    identifier !== "" &&
    url.trim() !== "" &&
    (authType !== "api_key" || headerName.trim() !== "") &&
    !missingToken &&
    (!oauth || !ownApp || clientId.trim() !== "") &&
    headers.every(
      (header) => header.name.trim() !== "" && (!header.secret || header.value || savedSecret(header.name)),
    ) &&
    collisions.length === 0;

  function toolFilter(): Pick<McpServerWrite, "toolInclude" | "toolExclude"> {
    if (!probe) return {};
    const shown = shownTools.filter((tool) => tool.visible).map((tool) => tool.name);
    if (hideNewTools) return { toolInclude: shown, toolExclude: null };
    const hidden = shownTools.filter((tool) => !tool.visible).map((tool) => tool.name);
    return hidden.length ? { toolInclude: null, toolExclude: hidden } : { toolInclude: null, toolExclude: null };
  }

  function payload(): McpServerWrite {
    const auth: NonNullable<McpServerWrite["auth"]> = { type: authType };
    if (authType === "api_key") auth.headerName = headerName.trim();
    if ((authType === "bearer" || authType === "api_key") && token) auth.token = token;
    if (oauth) {
      if (ownApp && clientId.trim()) auth.clientId = clientId.trim();
      if (ownApp && clientSecret) auth.clientSecret = clientSecret;
      if (oauthScope.trim()) auth.scope = oauthScope.trim();
    }
    return {
      name: name.trim(),
      description: description.trim() || null,
      url: url.trim(),
      ...(forAgent ? {} : { scope, restricted }),
      enabled,
      auth,
      headers: headersPayload(headers),
      // A saved server keeps its filter unless the Admin changed the tool choice.
      ...(server && !filterTouched ? {} : toolFilter()),
    };
  }

  async function runTest() {
    try {
      const result = await test.mutateAsync({
        id: server?.id,
        data: payload(),
      });
      setProbe(result);
      setVisible((current) =>
        Object.fromEntries(result.tools.map((tool) => [tool.name, current[tool.name] ?? tool.visible])),
      );
    } catch {
      // Shown from test.error. The last good result stays, so the tools chosen from it are
      // still what a save sends; clearing it would save the server with every tool visible.
    }
  }

  async function submit() {
    try {
      await save.mutateAsync({ id: server?.id, data: payload() });
      onOpenChange(false);
    } catch {
      // Shown inline from save.error.
    }
  }

  function toggleTool(toolName: string, checked: boolean) {
    setVisible((current) => ({ ...current, [toolName]: checked }));
    setFilterTouched(true);
  }

  const probeWarnings = (probe?.warnings ?? []).filter(
    (warning) => !FILTER_DEPENDENT_WARNINGS.some((prefix) => warning.startsWith(prefix)),
  );
  const unknownFilterNames =
    probe && !filterTouched && server
      ? (server.toolInclude ?? server.toolExclude ?? []).filter(
          (toolName) => !probe.tools.some((tool) => tool.name === toolName),
        )
      : [];

  const toolHint = probe
    ? `${probe.serverName ?? "Server"}${probe.serverVersion ? ` ${probe.serverVersion}` : ""} · protocol ${probe.protocolVersion}`
    : !canTest
      ? forAgent
        ? server
          ? "Sign the Agent in from its MCP servers to test it and choose tools."
          : "Save the server, then sign the Agent in to test it and choose tools."
        : server
          ? "Sign in for the organization from the server list to test it and choose tools."
          : "Save the server, then sign in for the organization to test it and choose tools."
      : server
        ? "Test the connection to change which tools Agents see."
        : "Test the connection to see the server's tools and choose which Agents see.";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[90vh] flex-col gap-0 p-0 sm:max-w-[42rem]">
        <DialogHeader className="border-b px-6 pt-5 pb-4" style={{ borderColor: "var(--line)" }}>
          <div className="flex items-center gap-3">
            <McpServerIcon />
            <div className="min-w-0">
              <DialogTitle>
                {server ? `Edit ${server.name}` : forAgent ? "Add an MCP server for this Agent" : "Add MCP server"}
              </DialogTitle>
              <DialogDescription className="mt-0.5">
                {forAgent ? "Only this Agent uses it. " : ""}
                Agents reach this server through Agent Barn&apos;s credential gateway, so its credential never enters an
                Agent.
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <div className="flex flex-1 flex-col gap-5 overflow-y-auto px-6 py-5">
          <div className="flex flex-col gap-3.5">
            <McpField
              id="mcp-name"
              label="Name"
              hint={
                <>
                  Identifier: <span className="font-mono">{identifier || "—"}</span>
                  {server ? " (never changes)" : " (fixed once saved; Agents see tools as identifier__tool)"}
                </>
              }
            >
              <input
                id="mcp-name"
                className="af-input w-full"
                value={name}
                maxLength={120}
                placeholder="e.g. Linear"
                autoComplete="off"
                onChange={(e) => setName(e.target.value)}
              />
            </McpField>
            <McpField
              id="mcp-url"
              label="Server URL"
              hint="A public HTTPS Streamable HTTP endpoint, without a query string."
            >
              <input
                id="mcp-url"
                className="af-input w-full font-mono text-[0.8rem]"
                value={url}
                maxLength={2048}
                placeholder="https://mcp.example.com/mcp"
                autoComplete="off"
                onChange={(e) => setUrl(e.target.value)}
              />
            </McpField>
            <McpField id="mcp-description" label="Description (optional)">
              <textarea
                id="mcp-description"
                className="af-input w-full resize-y"
                value={description}
                maxLength={500}
                rows={2}
                placeholder="What Agents can do with it"
                onChange={(e) => setDescription(e.target.value)}
              />
            </McpField>
          </div>

          <McpFieldGroup title="Credential" description="How Agent Barn signs in to the server on the Agents' behalf.">
            <McpCredentialFields
              idPrefix="mcp"
              authType={authType}
              onAuthTypeChange={setAuthType}
              allowOAuth
              headerName={headerName}
              onHeaderNameChange={setHeaderName}
              token={token}
              onTokenChange={setToken}
              tokenSaved={tokenSaved}
              headers={headers}
              onHeadersChange={setHeaders}
              savedSecret={savedSecret}
            />
            {oauth && (
              <section aria-label="OAuth sign-in" className="flex flex-col gap-3">
                <McpNotice>
                  {forAgent
                    ? "The Agent acts as the account you sign in with. Saving checks that the server offers OAuth sign-in and registers Agent Barn with it; sign the Agent in from its MCP servers afterwards, then test the connection and choose tools."
                    : "Agents act as the account someone signs in with: an Owner or Admin for the organization, or an Agent's editor for that Agent. Saving checks that the server offers OAuth sign-in and registers Agent Barn with it; sign in from the server list afterwards, then test the connection and choose tools."}
                </McpNotice>
                <label className="flex items-center gap-2 text-[0.84rem] text-[var(--ink-2)]">
                  <Checkbox checked={ownApp} onCheckedChange={(checked) => setOwnApp(checked === true)} />
                  Use my own OAuth app
                </label>
                {ownApp && (
                  <div className="flex flex-col gap-3.5 rounded-xl border p-3.5" style={{ borderColor: "var(--line)" }}>
                    <p className="m-0 text-[0.76rem] text-[var(--ink-4)]">
                      Only for servers that don&apos;t let Agent Barn register itself, such as GitHub. Register an app
                      with the server whose redirect URI is <span className="font-mono">{redirectUri}</span>.
                    </p>
                    <McpField id="mcp-client-id" label="Client ID">
                      <input
                        id="mcp-client-id"
                        className="af-input w-full"
                        value={clientId}
                        maxLength={1024}
                        autoComplete="off"
                        onChange={(e) => setClientId(e.target.value)}
                      />
                    </McpField>
                    <McpField id="mcp-client-secret" label="Client secret (optional)">
                      <input
                        id="mcp-client-secret"
                        type="password"
                        autoComplete="off"
                        className="af-input w-full"
                        value={clientSecret}
                        maxLength={8192}
                        placeholder={ownAppSaved ? "Saved — leave blank to keep it" : ""}
                        onChange={(e) => setClientSecret(e.target.value)}
                      />
                    </McpField>
                  </div>
                )}
                <McpField
                  id="mcp-scope"
                  label="Scopes (optional)"
                  hint={
                    server && server.oauthRegistered && !ownApp ? (
                      <>
                        Registered automatically as client <span className="font-mono">{server.oauthClientId}</span>.
                      </>
                    ) : undefined
                  }
                >
                  <input
                    id="mcp-scope"
                    className="af-input w-full"
                    value={oauthScope}
                    maxLength={1024}
                    placeholder="The server's own choice"
                    onChange={(e) => setOauthScope(e.target.value)}
                  />
                </McpField>
              </section>
            )}
          </McpFieldGroup>

          <McpFieldGroup title="Access">
            {!forAgent && (
              <>
                <fieldset className="m-0 grid gap-2 border-0 p-0 sm:grid-cols-2">
                  <legend className="sr-only">Which Agents may use it</legend>
                  {(
                    [
                      ["selected_agents", "Selected Agents", "An Agent's editor turns it on for that Agent."],
                      ["all_agents", "All Agents", "Every Agent in the organization, with no opt-out."],
                    ] as const
                  ).map(([value, label, hint]) => (
                    <label
                      key={value}
                      className="flex cursor-pointer items-start gap-2.5 rounded-xl border p-3 text-[0.86rem] transition-colors"
                      style={{
                        borderColor: scope === value ? "var(--ink)" : "var(--line)",
                        background: scope === value ? "var(--bg-soft)" : "transparent",
                      }}
                    >
                      <input
                        type="radio"
                        name="mcp-scope"
                        className="mt-1 accent-[var(--ink)]"
                        checked={scope === value}
                        onChange={() => setScope(value)}
                      />
                      <span>
                        <span className="font-medium text-[var(--ink)]">{label}</span>
                        <span className="block text-[0.76rem] text-[var(--ink-4)]">{hint}</span>
                      </span>
                    </label>
                  ))}
                </fieldset>
                {scope === "all_agents" && (
                  <McpNotice tone="warn" title="Every Agent acts with this credential">
                    Anyone who can create or edit an Agent can use the server&apos;s tools through it, limited to the
                    tools you leave visible below.
                  </McpNotice>
                )}
                <SwitchRow
                  title="Restricted"
                  description="Only Owners and Admins can turn it on for an Agent or give an Agent its own credential for it. Otherwise any Agent's editor can."
                >
                  <McpSwitch checked={restricted} label="Restricted" onChange={setRestricted} />
                </SwitchRow>
              </>
            )}
            <SwitchRow
              title="Enabled"
              description={
                forAgent
                  ? "Turning it off cuts the Agent off at once; it stays saved."
                  : "Turning it off cuts Agents off at once; it stays saved."
              }
            >
              <McpSwitch checked={enabled} label="Enabled" onChange={setEnabled} />
            </SwitchRow>
          </McpFieldGroup>

          <section
            aria-label="Tools"
            className="flex flex-col gap-3 border-t pt-4"
            style={{ borderColor: "var(--line)" }}
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <h3 className="m-0 text-[0.86rem] font-semibold text-[var(--ink)]">Tools</h3>
                <p className="mb-0 mt-0.5 text-[0.78rem] text-[var(--ink-3)]">{toolHint}</p>
              </div>
              <button
                type="button"
                className="af-btn af-btn-sm"
                disabled={!url.trim() || test.isPending || !canTest}
                onClick={() => void runTest()}
              >
                {test.isPending ? <Loader2 size={13} className="animate-spin" /> : <PlugZap size={13} />}
                Test connection
              </button>
            </div>
            {test.error && (
              <McpNotice tone="error" title="Connection failed">
                {errorMessage(test.error)}
              </McpNotice>
            )}
            {probe && shownTools.length > 0 && (
              <>
                <ul
                  className="m-0 flex list-none flex-col overflow-hidden rounded-xl border p-0"
                  style={{ borderColor: "var(--line)" }}
                >
                  {shownTools.map((tool, index) => (
                    <li
                      key={tool.name}
                      className="flex items-start gap-2.5 px-3.5 py-2.5"
                      style={{ borderTop: index ? "1px solid var(--line)" : undefined }}
                    >
                      <Checkbox
                        id={`mcp-tool-${tool.name}`}
                        className="mt-0.5"
                        checked={tool.visible}
                        aria-label={`${tool.name} visible to Agents`}
                        onCheckedChange={(checked) => toggleTool(tool.name, checked === true)}
                      />
                      <label htmlFor={`mcp-tool-${tool.name}`} className="min-w-0 text-[0.84rem]">
                        <span className="font-mono text-[var(--ink)]">{tool.name}</span>
                        {tool.description && (
                          <span className="block text-[0.76rem] text-[var(--ink-4)]">{tool.description}</span>
                        )}
                        {tool.truncated && (
                          <span className="block text-[0.76rem] text-[var(--warn)]">
                            OpenClaw shortens it to <span className="font-mono">{tool.openclawName}</span>
                          </span>
                        )}
                      </label>
                    </li>
                  ))}
                </ul>
                <label className="flex items-center gap-2 text-[0.8rem] text-[var(--ink-2)]">
                  <Checkbox
                    checked={hideNewTools}
                    onCheckedChange={(checked) => {
                      setHideNewTools(checked === true);
                      setFilterTouched(true);
                    }}
                  />
                  Hide tools the server adds later
                </label>
                {visibleTools.length === 0 && <McpNotice tone="error">No tools are visible to Agents.</McpNotice>}
              </>
            )}
            {collisions.length > 0 && (
              <McpNotice tone="error" title="Tool names collide in OpenClaw">
                These visible tools would share a name once shortened to 64 characters; hide all but one of each:{" "}
                {collisions.join(", ")}
              </McpNotice>
            )}
            {probeWarnings.map((warning) => (
              <McpNotice key={warning} tone="warn">
                {warning}
              </McpNotice>
            ))}
            {unknownFilterNames.length > 0 && (
              <McpNotice tone="warn">
                The saved tool filter names tools this server no longer offers: {unknownFilterNames.join(", ")}.
              </McpNotice>
            )}
          </section>

          {save.error && (
            <McpNotice tone="error" title="Could not save the server">
              {errorMessage(save.error)}
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
            disabled={!canSubmit || save.isPending}
            onClick={() => void submit()}
          >
            {save.isPending && <Loader2 size={14} className="animate-spin" />}
            {save.isPending ? "Connecting and saving…" : server ? "Save changes" : "Add server"}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function SwitchRow({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-4">
      <div className="min-w-0">
        <p className="m-0 text-[0.84rem] font-medium text-[var(--ink)]">{title}</p>
        <p className="m-0 text-[0.76rem] text-[var(--ink-4)]">{description}</p>
      </div>
      {children}
    </div>
  );
}
