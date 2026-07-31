import { useCallback } from "react";

import type { IntegrationDraft } from "@/features/agents/integrations";
import type { SharedCredentialBrief } from "../schemas";

export function useSharedManualSwitch(
  items: IntegrationDraft[],
  onChange: (items: IntegrationDraft[]) => void,
) {
  const switchToShared = useCallback(
    (provider: string) => {
      onChange(
        items.map((d) =>
          d.provider === provider ? { ...d, content: {}, sharedCredentialId: "" } : d,
        ),
      );
    },
    [items, onChange],
  );

  const switchToManual = useCallback(
    (provider: string) => {
      onChange(
        items.map((d) =>
          d.provider === provider ? { ...d, sharedCredentialId: undefined } : d,
        ),
      );
    },
    [items, onChange],
  );

  const handlePickShared = useCallback(
    (provider: string, brief: SharedCredentialBrief | null) => {
      onChange(
        items.map((d) =>
          d.provider === provider ? { ...d, sharedCredentialId: brief?.id ?? "" } : d,
        ),
      );
    },
    [items, onChange],
  );

  return { switchToShared, switchToManual, handlePickShared };
}
