"use client";

import { SharedCredentialPicker } from "./shared-credential-picker";
import type { SharedCredentialBrief } from "../schemas";

interface SharedManualToggleProps {
  provider: string;
  useShared: boolean;
  selectedId?: string;
  onSwitchToManual: () => void;
  onSwitchToShared: () => void;
  onPickShared: (brief: SharedCredentialBrief | null) => void;
}

const ACTIVE_STYLE = { background: "var(--ink)", color: "var(--bg)", borderColor: "var(--ink)" };

export function SharedManualToggle({
  provider,
  useShared,
  selectedId,
  onSwitchToManual,
  onSwitchToShared,
  onPickShared,
}: SharedManualToggleProps) {
  return (
    <>
      <div className="flex gap-1.5">
        <button
          type="button"
          className="af-btn af-btn-sm"
          style={!useShared ? ACTIVE_STYLE : undefined}
          onClick={onSwitchToManual}
        >
          Enter credentials
        </button>
        <button
          type="button"
          className="af-btn af-btn-sm"
          style={useShared ? ACTIVE_STYLE : undefined}
          onClick={onSwitchToShared}
        >
          Use shared credential
        </button>
      </div>
      {useShared && (
        <SharedCredentialPicker
          provider={provider}
          value={selectedId}
          onChange={onPickShared}
        />
      )}
    </>
  );
}
