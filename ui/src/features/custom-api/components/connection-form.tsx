"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
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
import { Checkbox } from "@/components/ui/checkbox";

import { ConnectionHeaders } from "./connection-headers";

import type { CustomApiConnection, CustomApiWrite } from "../schemas";

export function ConnectionForm({
  connection,
  pending,
  onSave,
  onCancel,
}: {
  connection?: CustomApiConnection;
  pending: boolean;
  onSave: (data: CustomApiWrite) => void;
  onCancel: () => void;
}) {
  const [slug, setSlug] = useState(connection?.slug ?? "");
  const [name, setName] = useState(connection?.name ?? "");
  const [baseUrl, setBaseUrl] = useState(connection?.baseUrl ?? "");
  const [isolated, setIsolated] = useState(connection?.isolated ?? false);
  const [authType, setAuthType] = useState<CustomApiWrite["auth"]["type"]>(
    connection?.authType ?? "none",
  );
  const [headerName, setHeaderName] = useState(
    connection?.authHeaderName ?? "X-API-Key",
  );
  const [token, setToken] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [headers, setHeaders] = useState(
    () =>
      connection?.headers.map((h) => ({ ...h, value: h.value ?? "" })) ?? [],
  );
  const retainsToken =
    connection?.authType === authType &&
    (authType !== "api_key" ||
      connection.authHeaderName?.toLowerCase() === headerName.toLowerCase());
  const prefix = `custom-api-${connection?.id ?? "new"}`;
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        onSave({
          ...(connection ? {} : { slug }),
          name,
          baseUrl,
          isolated,
          auth: {
            type: authType,
            ...(authType === "api_key" ? { headerName } : {}),
            ...((authType === "bearer" || authType === "api_key") && token
              ? { token }
              : {}),
            ...(authType === "basic" && username ? { username } : {}),
            ...(authType === "basic" && password ? { password } : {}),
          },
          headers: headers.map((h) => ({
            name: h.name,
            secret: h.secret,
            ...(!h.secret || h.value ? { value: h.value } : {}),
          })),
        });
      }}
      aria-label="Custom API connection"
      className="space-y-4 rounded-xl border p-4"
    >
      <fieldset disabled={pending} className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor={`${prefix}-name`}>Connection name</Label>
            <Input
              id={`${prefix}-name`}
              required
              maxLength={120}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor={`${prefix}-slug`}>Stable identifier</Label>
            <Input
              id={`${prefix}-slug`}
              required
              maxLength={64}
              pattern="[a-z][a-z0-9_-]{0,63}"
              disabled={Boolean(connection)}
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              placeholder="inventory"
            />
          </div>
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
          headers={headers}
          savedHeaders={connection?.headers}
          setHeaders={setHeaders}
        />
        <div className="flex items-center gap-3">
          <Checkbox
            id={`${prefix}-isolation`}
            checked={isolated}
            onCheckedChange={(checked) => setIsolated(checked === true)}
          />
          <Label htmlFor={`${prefix}-isolation`}>Isolate credentials</Label>
        </div>
        <p className="text-sm text-muted-foreground">
          {isolated
            ? "Credentials stay in Agent Barn. This Agent sends requests through the credential gateway."
            : "This Agent receives credentials and connects directly. Enable isolation to keep credentials outside the Agent."}
        </p>
        <div className="flex gap-2">
          <Button type="submit">
            {pending ? "Saving…" : "Save connection"}
          </Button>
          <Button type="button" variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        </div>
      </fieldset>
    </form>
  );
}
