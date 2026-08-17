"use client";

import { useState } from "react";

import { Textarea } from "@/components/ui/textarea";
import type { PlatformTemplateFileKey } from "@/features/platform-templates/utils";
import { PlatformTemplateArtifactTabs } from "@/features/platform-templates/components/platform-template-artifact-tabs";

import type { Snapshot } from "./agent-configuration-utils";

export function ConfigurationArtifactSurface({
  snapshot,
  editable = false,
  values,
  onChange,
}: {
  snapshot: Snapshot;
  editable?: boolean;
  values?: Partial<Record<PlatformTemplateFileKey, string>>;
  onChange?: (artifact: PlatformTemplateFileKey, value: string) => void;
}) {
  const [selectedArtifact, setSelectedArtifact] =
    useState<PlatformTemplateFileKey>("soulMd");

  return (
    <PlatformTemplateArtifactTabs
      value={selectedArtifact}
      onValueChange={setSelectedArtifact}
      renderContent={({ key, label }) => {
        const isSelected = key === selectedArtifact;
        const content =
          isSelected && editable ? values?.[key] ?? snapshot[key] : snapshot[key];

        return (
          <Textarea
            aria-label={`${label} content`}
            value={content}
            readOnly={!editable}
            onChange={
              isSelected && editable
                ? (event) => onChange?.(key, event.target.value)
                : undefined
            }
            rows={18}
            className={`min-h-[24rem] resize-y font-mono text-[0.8rem] leading-[1.55]${
              editable ? "" : " bg-[var(--bg-soft)]"
            }`}
          />
        );
      }}
    />
  );
}
