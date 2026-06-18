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
  const [input, setInput] = useState("");
  const [visible, setVisible] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSave = async () => {
    if (!input.trim()) return;
    setError(null);
    try {
      await saveToken.mutateAsync(input.trim());
      setInput("");
      setEditing(false);
      setVisible(false);
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? e?.message ?? "Failed to save token");
    }
  };

  const handleDelete = async () => {
    setError(null);
    try {
      await deleteToken.mutateAsync();
      setInput("");
      setEditing(false);
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? e?.message ?? "Failed to remove token");
    }
  };

  const handleCancel = () => {
    setInput("");
    setEditing(false);
    setError(null);
    setVisible(false);
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
        Slack configuration token
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
                  style={{ color: "var(--accent)" }}
                >
                  api.slack.com/apps
                </a>
              </li>
              <li>Click any app (or create a temporary one)</li>
              <li>Go to &quot;Basic Information&quot; &rarr; scroll to &quot;App Configuration Tokens&quot;</li>
              <li>Click &quot;Generate Token&quot; to create a configuration access token</li>
              <li>Copy and paste it below</li>
            </ol>
          </div>

          <div className="relative mb-3">
            <input
              className="af-input font-mono text-[13px] pr-10"
              type={visible ? "text" : "password"}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Paste configuration token..."
              autoComplete="off"
              data-lpignore="true"
              data-1p-ignore
              data-form-type="other"
              onKeyDown={(e) => {
                if (e.key === "Enter") void handleSave();
              }}
            />
            <button
              type="button"
              className="absolute right-3 top-1/2 -translate-y-1/2"
              style={{ color: "var(--ink-4)" }}
              onClick={() => setVisible((v) => !v)}
              tabIndex={-1}
            >
              {visible ? <EyeOffIcon size={15} /> : <EyeIcon size={15} />}
            </button>
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
              disabled={!input.trim() || saveToken.isPending}
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
