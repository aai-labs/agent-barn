"use client";

import { useState } from "react";

import { AgentDefaultModelSection } from "./agent-default-model-section";
import { AgentModelMapSection } from "./agent-model-map-section";
import { AllowedModelsSection } from "./allowed-models-section";

type SectionKey = "default-model" | "allowed-models";

/**
 * Both model controls in one place. They are one contract: the default has to stay
 * inside the allowed list, and the API enforces that from both directions, so editing
 * them on separate pages only produced avoidable 400s.
 */
export function AgentDefaultsPanel({ canEdit }: { canEdit: boolean }) {
  // One section edits at a time, matching the Agent configuration page.
  const [editing, setEditing] = useState<SectionKey | null>(null);

  const toggle = (section: SectionKey) => () =>
    setEditing((current) => (current === section ? null : section));

  return (
    <div className="flex flex-col gap-5">
      <AgentDefaultModelSection
        canEdit={canEdit}
        editing={editing === "default-model"}
        onEdit={toggle("default-model")}
      />
      <AllowedModelsSection
        canEdit={canEdit}
        editing={editing === "allowed-models"}
        onEdit={toggle("allowed-models")}
      />
      <AgentModelMapSection />
    </div>
  );
}
