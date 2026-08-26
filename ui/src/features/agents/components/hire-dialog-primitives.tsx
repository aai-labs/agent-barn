"use client";

import React, { useRef, useState } from "react";
import { EyeIcon, EyeOffIcon, PlusIcon, XIcon } from "@/components/icons";
import { useGoogleOAuth, type GoogleOAuthResult } from "../hooks/use-google-oauth";

export function DialogShell({
  children,
  shadeClick,
}: {
  children: React.ReactNode;
  shadeClick: (() => void) | undefined;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div
        className="absolute inset-0"
        style={{ background: "rgba(20,16,10,.4)" }}
        onClick={shadeClick}
      />
      <div
        className="relative flex flex-col w-full max-w-4xl max-h-[90vh] rounded-2xl shadow-2xl"
        style={{ background: "var(--bg-elev)" }}
      >
        {children}
      </div>
    </div>
  );
}

export function ChoiceCard({
  selected,
  onClick,
  title,
  description,
}: {
  selected: boolean;
  onClick: () => void;
  title: string;
  description: string;
}) {
  return (
    <div
      className="flex flex-col gap-1 p-4 rounded-2xl cursor-default transition-colors"
      style={{
        border: selected ? "1.5px solid var(--ink)" : "1.5px solid var(--line)",
        background: selected ? "var(--bg-soft)" : "var(--bg-elev)",
      }}
      onClick={onClick}
    >
      <div className="font-semibold text-[0.9375rem]" style={{ color: "var(--ink)" }}>{title}</div>
      <div className="text-[0.8125rem] leading-[1.45]" style={{ color: "var(--ink-3)" }}>{description}</div>
    </div>
  );
}

export function FormField({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="font-medium text-[0.844rem]" style={{ color: "var(--ink)" }}>
        {label}
      </label>
      {children}
      {hint && (
        <span className="text-xs" style={{ color: "var(--ink-4)" }}>
          {hint}
        </span>
      )}
    </div>
  );
}

export function TokenInput({
  value,
  onChange,
  visible,
  onToggle,
  placeholder,
  disabled,
}: {
  value: string;
  onChange: (v: string) => void;
  visible: boolean;
  onToggle: () => void;
  placeholder?: string;
  disabled?: boolean;
}) {
  return (
    <div className="relative">
      <input
        className="af-input font-mono text-[0.8125rem] pr-10"
        type={visible ? "text" : "password"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoComplete="off"
        data-lpignore="true"
        data-1p-ignore
        data-form-type="other"
        disabled={disabled}
      />
      <button
        type="button"
        className="absolute right-3 top-1/2 -translate-y-1/2"
        style={{ color: "var(--ink-4)" }}
        onClick={onToggle}
        tabIndex={-1}
      >
        {visible ? <EyeOffIcon size={15} /> : <EyeIcon size={15} />}
      </button>
    </div>
  );
}

function GoogleGlyph({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 18 18" aria-hidden focusable="false">
      <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62Z" />
      <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.8.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.33A9 9 0 0 0 9 18Z" />
      <path fill="#FBBC05" d="M3.97 10.72a5.4 5.4 0 0 1 0-3.44V4.95H.96a9 9 0 0 0 0 8.1l3.01-2.33Z" />
      <path fill="#EA4335" d="M9 3.58c1.32 0 2.5.46 3.44 1.35l2.58-2.58C13.47.89 11.43 0 9 0A9 9 0 0 0 .96 4.95l3.01 2.33C4.68 5.16 6.66 3.58 9 3.58Z" />
    </svg>
  );
}

/**
 * "Authenticate with Google" button that runs the OAuth popup flow and hands the
 * captured refresh token to the caller via onConnected. Replaces manual client
 * id/secret/refresh-token entry for the Google integrations.
 *
 * ``provider`` picks which integration is being connected, and so which scopes Google
 * is asked for; ``connectedEmail`` identifies the account when available, with
 * ``connectedNote`` as the fallback.
 */
export function GoogleAuthButton({
  connected,
  onConnected,
  disabled,
  disabledNote,
  provider = "google_workspace",
  connectedNote = "Google account connected",
  connectedEmail,
  authorizeParams,
  requireEmail = false,
}: {
  connected: boolean;
  onConnected: (result: GoogleOAuthResult) => void;
  disabled?: boolean;
  // Why the button is unavailable, e.g. a prerequisite field is still empty.
  disabledNote?: string;
  provider?: string;
  connectedNote?: string;
  connectedEmail?: string;
  // Extra query params for /authorize-url (google_workspace derives its scopes from
  // the selected services rather than having a fixed per-provider scope list).
  authorizeParams?: Record<string, string>;
  // Providers whose stored credential is keyed by account email (google_workspace)
  // cannot accept a connection that didn't report one.
  requireEmail?: boolean;
}) {
  const { connectGoogle, isConnecting } = useGoogleOAuth();
  // google_workspace expects the user's own OAuth client, so its help text is the full
  // setup walkthrough rather than a short "optional" aside. It is rendered inline and
  // above the connect button — never behind a disclosure — because the client id/secret
  // are a prerequisite for connecting, not an aside to go looking for. The toggle (and
  // this state) only apply to providers where bringing your own client is optional.
  const ownClientRequired = provider === "google_workspace";
  const [error, setError] = useState<string | null>(null);
  const [showCustom, setShowCustom] = useState(false);
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [showSecret, setShowSecret] = useState(false);
  const clientFileRef = useRef<HTMLInputElement>(null);

  const redirectUri =
    typeof window !== "undefined"
      ? `${window.location.origin}/api/v1/integrations/google/callback`
      : "";

  async function handleClientFile(file: File) {
    setError(null);
    try {
      const parsed = JSON.parse(await file.text()) as {
        web?: { client_id?: string; client_secret?: string };
        installed?: unknown;
      };
      if (!parsed.web && parsed.installed) {
        setError(
          "That's a Desktop client. Create an OAuth client of type “Web application” instead, with this app's redirect URI.",
        );
        return;
      }
      const id = parsed.web?.client_id?.trim();
      const secret = parsed.web?.client_secret?.trim();
      if (!id || !secret) {
        setError("That file has no web client_id/client_secret. Download it again from the Cloud Console.");
        return;
      }
      setClientId(id);
      setClientSecret(secret);
    } catch {
      setError("Could not read that file — it must be the JSON downloaded from the Cloud Console.");
    }
  }

  async function handleClick() {
    setError(null);
    const id = clientId.trim();
    const secret = clientSecret.trim();
    // A custom client needs both halves; refuse a lopsided pair rather than silently
    // falling back to the shared client.
    if ((id || secret) && (!id || !secret)) {
      setError(
        "Enter both a client ID and secret, or leave both blank to use the shared app client.",
      );
      return;
    }
    if (ownClientRequired && (!id || !secret)) {
      setShowCustom(true);
      setError("Upload your Google OAuth client JSON (or paste its client ID and secret) first.");
      return;
    }
    const creds = id && secret ? { clientId: id, clientSecret: secret } : undefined;
    try {
      const result = await connectGoogle(creds, provider, authorizeParams);
      if (requireEmail && !result.email) {
        setError("Google did not report the account's email address. Please reconnect.");
        return;
      }
      onConnected(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed.");
    }
  }

  return (
    <div className="flex flex-col gap-2">
      {ownClientRequired ? (
        <span className="text-[0.75rem] font-medium self-start" style={{ color: "var(--ink-3)" }}>
          Your Google OAuth client (required)
        </span>
      ) : (
        <button
          type="button"
          className="text-[0.75rem] self-start"
          style={{ color: "var(--ink-4)" }}
          onClick={() => setShowCustom((v) => !v)}
          disabled={disabled || isConnecting}
        >
          {showCustom ? "▾" : "▸"} Use your own Google client (optional)
        </button>
      )}
      {(ownClientRequired || showCustom) && (
        <div className="flex flex-col gap-2.5 pl-3" style={{ borderLeft: "2px solid var(--line)" }}>
          {ownClientRequired ? (
            <div className="text-[0.75rem] leading-[1.5] flex flex-col gap-1.5" style={{ color: "var(--ink-4)" }}>
              <p>
                This integration uses <strong>your own</strong> Google OAuth client, so the access
                stays inside your Google project. One-time setup in the{" "}
                <a
                  href="https://console.cloud.google.com/apis/credentials"
                  target="_blank"
                  rel="noreferrer"
                  className="underline"
                >
                  Google Cloud Console
                </a>
                :
              </p>
              <ol className="list-decimal pl-4 flex flex-col gap-1">
                <li>Create (or pick) a Google Cloud project.</li>
                <li>Enable the APIs for the services you selected above — Gmail, Calendar, Drive, Sheets.</li>
                <li>
                  On the OAuth consent screen, set publishing status to <strong>Production</strong>{" "}
                  (or <strong>Internal</strong> for a Workspace org). Leaving it in{" "}
                  <em>Testing</em> makes Google expire the connection every 7 days.
                </li>
                <li>
                  Create an OAuth client ID of type <strong>Web application</strong> and add{" "}
                  <code className="break-all">{redirectUri}</code> as an authorized redirect URI.
                </li>
                <li>Download its JSON and upload it below.</li>
              </ol>
              <p>
                On first connect Google will warn that the app is unverified — that app is your own,
                so continue past it.
              </p>
            </div>
          ) : (
            <p className="text-[0.75rem] leading-[1.5]" style={{ color: "var(--ink-4)" }}>
              In the{" "}
              <a
                href="https://console.cloud.google.com/apis/credentials"
                target="_blank"
                rel="noreferrer"
                className="underline"
              >
                Google Cloud Console
              </a>{" "}
              create an OAuth 2.0 Client ID of type <strong>Web application</strong>, enable the
              APIs for the services you need, and add{" "}
              <code className="break-all">{redirectUri}</code> as an authorized redirect URI. Then
              paste the client ID and secret below — leave both blank to use the shared app client.
            </p>
          )}
          <FormField label="Client JSON" hint="Reads the client ID and secret out of the downloaded file.">
            <input
              ref={clientFileRef}
              type="file"
              accept=".json,application/json"
              className="af-input text-[0.8125rem]"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void handleClientFile(file);
              }}
              disabled={disabled || isConnecting}
            />
          </FormField>
          <FormField label="Client ID">
            <input
              className="af-input font-mono text-[0.8125rem]"
              value={clientId}
              onChange={(e) => setClientId(e.target.value)}
              placeholder="1234567890-abc….apps.googleusercontent.com"
              autoComplete="off"
              disabled={disabled || isConnecting}
            />
          </FormField>
          <FormField label="Client secret">
            <TokenInput
              value={clientSecret}
              onChange={setClientSecret}
              visible={showSecret}
              onToggle={() => setShowSecret((v) => !v)}
              placeholder="GOCSPX-…"
              disabled={disabled || isConnecting}
            />
          </FormField>
        </div>
      )}

      <button
        type="button"
        className="af-btn af-btn-sm flex items-center gap-2 self-start"
        onClick={handleClick}
        disabled={disabled || isConnecting}
      >
        <GoogleGlyph size={15} />
        {isConnecting
          ? "Waiting for Google…"
          : connected
            ? "Reconnect Google account"
            : "Authenticate with Google"}
      </button>
      {connected && !isConnecting && (
        <span className="text-[0.75rem] font-medium" style={{ color: "var(--ok, #2f855a)" }}>
          {connectedEmail ? `✓ Connected as ${connectedEmail}` : `✓ Connected — ${connectedNote}`}
        </span>
      )}
      {disabled && disabledNote && !isConnecting && (
        <span className="text-[0.75rem]" style={{ color: "var(--ink-4)" }}>
          {disabledNote}
        </span>
      )}
      {error && (
        <span className="text-[0.75rem]" style={{ color: "var(--danger, #c53030)" }}>
          {error}
        </span>
      )}
    </div>
  );
}

export function NextStep({
  n,
  label,
  children,
}: {
  n: number;
  label: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex gap-3 items-start">
      <div
        className="w-5 h-5 rounded-full flex-shrink-0 grid place-items-center text-[0.656rem] font-bold mt-0.5"
        style={{ background: "var(--bg-elev)", border: "1px solid var(--line)", color: "var(--ink-3)" }}
      >
        {n}
      </div>
      <div>
        <div className="font-medium text-[0.8125rem] mb-0.5" style={{ color: "var(--ink)" }}>{label}</div>
        {children && (
          <div className="text-[0.781rem] leading-[1.5]" style={{ color: "var(--ink-3)" }}>{children}</div>
        )}
      </div>
    </div>
  );
}

export function RepoListField({
  repos,
  onChange,
  placeholder,
}: {
  repos: string[];
  onChange: (repos: string[]) => void;
  placeholder?: string;
}) {
  const [draft, setDraft] = useState("");

  function addRepo() {
    const trimmed = draft.trim();
    if (trimmed && !repos.includes(trimmed)) {
      onChange([...repos, trimmed]);
    }
    setDraft("");
  }

  return (
    <div className="flex flex-col gap-2">
      {repos.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {repos.map((repo) => (
            <span
              key={repo}
              className="inline-flex items-center gap-1 text-[0.781rem] px-2.5 py-1 rounded-full"
              style={{ background: "var(--bg-elev)", border: "1px solid var(--line)", color: "var(--ink-2)" }}
            >
              {repo}
              <button
                type="button"
                className="ml-0.5 rounded-full flex items-center"
                style={{ color: "var(--ink-4)" }}
                onClick={() => onChange(repos.filter((r) => r !== repo))}
                aria-label={`Remove ${repo}`}
              >
                <XIcon style={{ width: 12, height: 12 }} />
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="flex items-stretch gap-2">
        <input
          className="af-input flex-1"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              addRepo();
            }
          }}
          placeholder={placeholder}
          autoComplete="off"
        />
        <button
          type="button"
          className="af-btn flex items-center gap-1"
          onClick={addRepo}
          disabled={!draft.trim()}
        >
          <PlusIcon size={14} /> Add
        </button>
      </div>
    </div>
  );
}
