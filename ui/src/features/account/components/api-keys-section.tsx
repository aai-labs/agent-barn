"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { ConfirmationDialog } from "@/components/confirmation-dialog";
import { api } from "@/shared/api";
import { apiKeysKey } from "@/shared/query-keys";
import { ApiKeyCreatedSchema, ApiKeyListSchema, type ApiKeyCreated, type ApiKeyRead } from "../api-key-schemas";

const url = "/api/v1/auth/me/api-keys";

export function ApiKeysSection() {
  const queryClient = useQueryClient();
  const { data: keys = [], isPending, error } = useQuery({
    queryKey: apiKeysKey.lists(),
    queryFn: async () => (await api.get<ApiKeyRead[]>(url, { schema: ApiKeyListSchema })).data,
  });
  const [name, setName] = useState("");
  const [mode, setMode] = useState<"READ_ONLY" | "FULL">("READ_ONLY");
  const [expiry, setExpiry] = useState("");
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);
  const [revoke, setRevoke] = useState<ApiKeyRead | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function createKey() {
    setBusy(true);
    setMessage(null);
    try {
      const result = await api.post<ApiKeyCreated>(url, {
        name: name.trim(),
        accessMode: mode,
        expiresAt: expiry ? new Date(`${expiry}T23:59:59`).toISOString() : null,
      }, { schema: ApiKeyCreatedSchema });
      setCreated(result.data);
      setName("");
      setMode("READ_ONLY");
      setExpiry("");
      void queryClient.invalidateQueries({ queryKey: apiKeysKey.all });
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : "Could not create API key");
    } finally {
      setBusy(false);
    }
  }

  async function revokeKey() {
    if (!revoke) return;
    setBusy(true);
    setMessage(null);
    try {
      await api.delete(`${url}/${revoke.id}`);
      setRevoke(null);
      void queryClient.invalidateQueries({ queryKey: apiKeysKey.all });
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : "Could not revoke API key");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="af-card p-6">
      <h2 className="font-semibold text-[15px] mb-1">Personal API keys</h2>
      <p className="text-[13.5px] mb-5" style={{ color: "var(--ink-3)" }}>
        Give your own agents access to AgentBarn. Keys use your current permissions across your organizations.
        Password changes invalidate your keys. <a className="underline" href="/api/v1/developer">API guide</a>
      </p>

      {created && <div className="rounded-lg p-4 mb-5" style={{ background: "var(--bg-soft)" }}>
        <p className="font-medium mb-2">Copy this key now. It will not be shown again.</p>
        <code className="block break-all text-sm mb-3">{created.token}</code>
        <button type="button" className="af-btn af-btn-sm mr-2" onClick={() => void navigator.clipboard.writeText(created.token)}>Copy key</button>
        <button type="button" className="af-btn af-btn-sm" onClick={() => setCreated(null)}>Done</button>
      </div>}

      <div className="grid gap-3 sm:grid-cols-[1fr_auto_auto_auto] items-end mb-5">
        <label className="text-xs">Name
          <input className="af-input mt-1" value={name} maxLength={100} onChange={(event) => setName(event.target.value)} placeholder="My automation" />
        </label>
        <div className="text-xs">Access
          <div className="flex gap-1 mt-1">
            <button type="button" className={`af-btn af-btn-sm ${mode === "READ_ONLY" ? "af-btn-primary" : ""}`} onClick={() => setMode("READ_ONLY")}>Read only</button>
            <button type="button" className={`af-btn af-btn-sm ${mode === "FULL" ? "af-btn-primary" : ""}`} onClick={() => setMode("FULL")}>Full</button>
          </div>
        </div>
        <label className="text-xs">Expires (optional)
          <input type="date" className="af-input mt-1" value={expiry} min={new Date().toISOString().slice(0, 10)} onChange={(event) => setExpiry(event.target.value)} />
        </label>
        <button type="button" className="af-btn af-btn-primary" disabled={!name.trim() || busy} onClick={() => void createKey()}>Create key</button>
      </div>
      {mode === "FULL" && <p className="text-xs mb-4" style={{ color: "var(--ink-3)" }}>Full access can change resources and create more keys wherever your account has permission.</p>}
      {message && <p role="alert" className="text-sm mb-3" style={{ color: "var(--err)" }}>{message}</p>}
      {error && <p role="alert" className="text-sm mb-3">Could not load API keys.</p>}
      {isPending ? <p className="text-sm">Loading keys…</p> : keys.length === 0 ? <p className="text-sm">No API keys yet.</p> : (
        <ul className="divide-y" style={{ borderColor: "var(--line)" }}>
          {keys.map((key) => <li key={key.id} className="py-3 flex flex-wrap gap-3 items-center justify-between">
            <div><div className="font-medium text-sm">{key.name} <code className="font-normal ml-2">{key.tokenPrefix}…</code></div>
              <div className="text-xs" style={{ color: "var(--ink-3)" }}>{key.accessMode === "FULL" ? "Full access" : "Read only"} · {key.status.toLowerCase()} · Last used {key.lastUsedAt ? new Date(key.lastUsedAt).toLocaleDateString() : "never"} · Expires {key.expiresAt ? new Date(key.expiresAt).toLocaleDateString() : "never"}</div>
            </div>
            {key.status === "ACTIVE" && <button type="button" className="af-btn af-btn-sm" onClick={() => setRevoke(key)}>Revoke</button>}
          </li>)}
        </ul>
      )}
      <ConfirmationDialog open={!!revoke} onOpenChange={(open) => { if (!open) setRevoke(null); }} title="Revoke API key" description={`Revoke ${revoke?.name ?? "this key"}? Requests using it will fail immediately.`} confirmLabel="Revoke key" onConfirm={revokeKey} isPending={busy} variant="destructive" />
    </section>
  );
}
