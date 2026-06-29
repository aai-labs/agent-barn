"use client";

import { useState } from "react";
import { useSlackConfigToken } from "../hooks/use-slack-config-token";
import { useSlackConfigTokenActions } from "../hooks/use-slack-config-token-actions";
import {
  EyeIcon,
  EyeOffIcon,
  AlertCircleIcon,
} from "@/components/icons";

export function SlackTokenSection() {
  const { hasToken, tokenPreview, isLoading } = useSlackConfigToken();
  const { saveToken, deleteToken } = useSlackConfigTokenActions();

  const [editing, setEditing] = useState(false);
  const [accessInput, setAccessInput] = useState("");
  const [refreshInput, setRefreshInput] = useState("");
  const [visibleAccess, setVisibleAccess] = useState(false);
  const [visibleRefresh, setVisibleRefresh] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSave = async () => {
    if (!accessInput.trim()) return;
    setError(null);
    try {
      await saveToken.mutateAsync({
        accessToken: accessInput.trim(),
        refreshToken: refreshInput.trim(),
      });
      setAccessInput("");
      setRefreshInput("");
      setEditing(false);
      setVisibleAccess(false);
      setVisibleRefresh(false);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to save token";
      setError(msg);
    }
  };

  const handleDelete = async () => {
    setError(null);
    try {
      await deleteToken.mutateAsync();
      setAccessInput("");
      setRefreshInput("");
      setEditing(false);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to remove token";
      setError(msg);
    }
  };

  const handleCancel = () => {
    setAccessInput("");
    setRefreshInput("");
    setEditing(false);
    setError(null);
    setVisibleAccess(false);
    setVisibleRefresh(false);
  };

  if (isLoading) {
    return (
      <div className="af-card p-6">
        <div className="text-[14px]" style={{ color: "var(--ink-3)" }}>Loading...</div>
      </div>
    );
  }

  const showInput = !hasToken || editing;

  return (
    <div className="af-card p-6">
      <div className="font-semibold text-[15px] mb-1" style={{ color: "var(--ink)" }}>
        Slack configuration tokens
      </div>
      <p className="text-[13.5px] leading-[1.55] mb-5" style={{ color: "var(--ink-3)" }}>
        Used to automatically create Slack apps when hiring agents. This avoids
        the manual setup at api.slack.com.
      </p>

      {showInput && (
        <>
          <div className="text-[13px] leading-[1.6] mb-4" style={{ color: "var(--ink-3)" }}>
            <ol className="list-decimal pl-4 space-y-1">
              <li>
                Go to{" "}
                <a
                  href="https://api.slack.com/apps"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline"
                  style={{ color: "var(--ink-2)" }}
                >
                  api.slack.com/apps
                </a>
              </li>
              <li>Scroll to &quot;App Configuration Tokens&quot; at the bottom of the page</li>
              <li>Click &quot;Generate Token&quot; — you will get an access token and a refresh token</li>
              <li>Copy and paste both below</li>
            </ol>
          </div>

          <div className="flex flex-col gap-3 mb-3">
            <div>
              <label className="block text-[12.5px] font-medium mb-1" style={{ color: "var(--ink-2)" }}>
                Access token
              </label>
              <div className="relative">
                <input
                  className="af-input font-mono text-[13px] pr-10"
                  type={visibleAccess ? "text" : "password"}
                  value={accessInput}
                  onChange={(e) => setAccessInput(e.target.value)}
                  placeholder="Configuration access token..."
                  autoComplete="off"
                  data-lpignore="true"
                  data-1p-ignore
                  data-form-type="other"
                />
                <button
                  type="button"
                  className="absolute right-3 top-1/2 -translate-y-1/2"
                  style={{ color: "var(--ink-4)" }}
                  onClick={() => setVisibleAccess((v) => !v)}
                  tabIndex={-1}
                >
                  {visibleAccess ? <EyeOffIcon size={15} /> : <EyeIcon size={15} />}
                </button>
              </div>
            </div>

            <div>
              <label className="block text-[12.5px] font-medium mb-1" style={{ color: "var(--ink-2)" }}>
                Refresh token <span className="font-normal" style={{ color: "var(--ink-4)" }}>(enables automatic renewal)</span>
              </label>
              <div className="relative">
                <input
                  className="af-input font-mono text-[13px] pr-10"
                  type={visibleRefresh ? "text" : "password"}
                  value={refreshInput}
                  onChange={(e) => setRefreshInput(e.target.value)}
                  placeholder="xoxe-…"
                  autoComplete="off"
                  data-lpignore="true"
                  data-1p-ignore
                  data-form-type="other"
                />
                <button
                  type="button"
                  className="absolute right-3 top-1/2 -translate-y-1/2"
                  style={{ color: "var(--ink-4)" }}
                  onClick={() => setVisibleRefresh((v) => !v)}
                  tabIndex={-1}
                >
                  {visibleRefresh ? <EyeOffIcon size={15} /> : <EyeIcon size={15} />}
                </button>
              </div>
            </div>
          </div>

          {error && (
            <div
              className="flex items-start gap-2 text-[13px] mb-3 leading-[1.5]"
              style={{ color: "var(--err)" }}
            >
              <AlertCircleIcon style={{ flexShrink: 0, marginTop: 2 }} />
              {error}
            </div>
          )}

          <div className="flex gap-2">
            <button
              className="af-btn af-btn-primary"
              disabled={!accessInput.trim() || !refreshInput.trim() || saveToken.isPending}
              onClick={() => void handleSave()}
            >
              {saveToken.isPending ? "Saving..." : "Save"}
            </button>
            {editing && (
              <button className="af-btn" onClick={handleCancel}>
                Cancel
              </button>
            )}
          </div>
        </>
      )}

      {hasToken && !editing && (
        <div className="flex items-center gap-3">
          <code
            className="text-[13px] px-3 py-2 rounded-lg flex-1"
            style={{ background: "var(--bg-soft)", color: "var(--ink-2)" }}
          >
            {tokenPreview ?? "****"}
          </code>
          <button className="af-btn af-btn-sm" onClick={() => setEditing(true)}>
            Update
          </button>
          <button
            className="af-btn af-btn-sm"
            style={{ borderColor: "var(--err)", color: "var(--err)" }}
            disabled={deleteToken.isPending}
            onClick={() => void handleDelete()}
          >
            {deleteToken.isPending ? "Removing..." : "Remove"}
          </button>
        </div>
      )}
    </div>
  );
}
