"use client";

import { IntegrationIsolationControl } from "@/features/agents/components/integration-isolation-control";
import type { Agent } from "@/features/agents/schemas";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { ConnectionHeaders } from "./connection-headers";

import type { CustomApiConnection, CustomApiWrite } from "../schemas";

export function ConnectionForm({
  agent,
  connection,
  value,
  onChange,
  prefix,
}: {
  agent: Agent;
  connection?: CustomApiConnection;
  value: CustomApiWrite;
  onChange: (value: CustomApiWrite) => void;
  prefix: string;
}) {
  const { name, baseUrl, isolated, headers, auth } = value;
  const authType = auth.type;
  const headerName = auth.headerName ?? "X-API-Key";
  const token = auth.token ?? "";
  const username = auth.username ?? "";
  const password = auth.password ?? "";
  const setName = (name: string) => onChange({ ...value, name });
  const setBaseUrl = (baseUrl: string) => onChange({ ...value, baseUrl });
  const setIsolated = (isolated: boolean) => onChange({ ...value, isolated });
  const setAuthType = (type: CustomApiWrite["auth"]["type"]) => onChange({ ...value, auth: { type, ...(type === "api_key" ? { headerName: "X-API-Key" } : {}) } });
  const setHeaderName = (headerName: string) => onChange({ ...value, auth: { ...auth, headerName } });
  const setToken = (token: string) => onChange({ ...value, auth: { ...auth, token } });
  const setUsername = (username: string) => onChange({ ...value, auth: { ...auth, username } });
  const setPassword = (password: string) => onChange({ ...value, auth: { ...auth, password } });
  const retainsToken =
    connection?.authType === authType &&
    (authType !== "api_key" ||
      connection.authHeaderName?.toLowerCase() === headerName.toLowerCase());
  return (
    <div className="flex flex-col gap-3.5" role="group" aria-label="Custom API connection">
        <div className="space-y-2">
          <Label htmlFor={`${prefix}-name`}>Connection name</Label>
          <Input id={`${prefix}-name`} required maxLength={120} value={name} onChange={(e) => setName(e.target.value)} />
          <p className="text-xs text-muted-foreground">Identifier: {connection?.slug ?? (name.toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^[-_]+|[-_]+$/g, "").slice(0, 64).replace(/[-_]+$/g, "") || "derived from the connection name")}</p>
        </div>
        <div className="space-y-2">
          <Label htmlFor={`${prefix}-url`}>Allowed base URL</Label>
          <Input
            id={`${prefix}-url`}
            type="url"
            maxLength={2048}
            required
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="https://api.example.com/v1"
          />
          <p className="text-sm text-muted-foreground">
            Public HTTPS only. Requests use full URLs within this origin and
            path. Redirects are refused.
          </p>
        </div>
        <div className="space-y-2">
          <Label htmlFor={`${prefix}-auth`}>Authentication</Label>
          <Select
            value={authType}
            onValueChange={(value) => setAuthType(value as typeof authType)}
          >
            <SelectTrigger id={`${prefix}-auth`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectItem value="none">No authentication</SelectItem>
                <SelectItem value="bearer">Bearer token</SelectItem>
                <SelectItem value="api_key">API key header</SelectItem>
                <SelectItem value="basic">Basic authentication</SelectItem>
              </SelectGroup>
            </SelectContent>
          </Select>
        </div>
        {authType === "api_key" && (
          <div className="space-y-2">
            <Label htmlFor={`${prefix}-header`}>
              Authentication header name
            </Label>
            <Input
              id={`${prefix}-header`}
              required
              value={headerName}
              onChange={(e) => setHeaderName(e.target.value)}
            />
            <p className="text-sm text-muted-foreground">
              For custom schemes, use Authorization and enter the complete
              value, such as Token …
            </p>
          </div>
        )}
        {(authType === "bearer" || authType === "api_key") && (
          <div className="space-y-2">
            <Label htmlFor={`${prefix}-token`}>API token</Label>
            <Input
              id={`${prefix}-token`}
              type="password"
              autoComplete="new-password"
              required={!retainsToken}
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder={
                retainsToken
                  ? "Leave blank to keep saved token"
                  : "Enter a new token"
              }
            />
          </div>
        )}
        {authType === "basic" && (
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor={`${prefix}-user`}>Username</Label>
              <Input
                id={`${prefix}-user`}
                autoComplete="off"
                required={!connection || connection.authType !== "basic"}
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder={
                  connection ? "Leave blank to keep saved username" : ""
                }
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor={`${prefix}-password`}>Password</Label>
              <Input
                id={`${prefix}-password`}
                type="password"
                autoComplete="new-password"
                required={!connection || connection.authType !== "basic"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={
                  connection ? "Leave blank to keep saved password" : ""
                }
              />
            </div>
          </div>
        )}
        <ConnectionHeaders
          prefix={prefix}
          headers={headers.map((header) => ({ ...header, value: header.value ?? "" }))}
          savedHeaders={connection?.headers}
          setHeaders={(headers) => onChange({ ...value, headers })}
        />
        <IntegrationIsolationControl agent={agent} isolated={isolated} onChange={setIsolated} secret={{
          provider: "custom_api", secretName: name || "Custom API", isolation: {
            desired: isolated, applied: connection?.appliedIsolated,
            pending: connection?.pendingApply ?? true, switchAvailable: true, supportedModes: ["direct", "isolated"],
            directDescription: "This Agent receives credentials and connects directly.",
            isolatedDescription: "Credentials stay in Agent Barn. This Agent sends requests through the credential gateway.",
          },
        }} />
    </div>
  );
}
