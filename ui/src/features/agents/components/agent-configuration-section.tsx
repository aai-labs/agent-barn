"use client";

import type { ReactNode } from "react";

import { SettingsSection } from "@/components/settings/settings-section";

/**
 * The Agent flavour of {@link SettingsSection}: same card and Apply flow, plus the
 * one thing that is specific to Agents — applying a change to a running Agent stops
 * and starts it, and the button and confirmation have to say so.
 */
export function AgentConfigurationSection({
  restartOnApply = false,
  ...props
}: {
  title: string;
  description: string;
  editing?: boolean;
  canEdit?: boolean;
  onEdit?: () => void;
  footer?: ReactNode;
  onApply?: () => void | Promise<void>;
  onCancel?: () => void;
  onApplied?: () => void;
  applyDisabled?: boolean;
  restartOnApply?: boolean;
  actionsRenderer?: (actions: ReactNode) => ReactNode;
  unstyled?: boolean;
  children: ReactNode;
}) {
  return (
    <SettingsSection
      {...props}
      applyLabel={restartOnApply ? "Apply & Restart" : "Apply"}
      applyPendingLabel={restartOnApply ? "Applying & Restarting…" : "Applying…"}
      confirm={
        restartOnApply
          ? {
              title: "Apply changes and restart the Agent?",
              description:
                "This saves the changes, stops the Agent, and starts it again with the updated configuration.",
            }
          : {
              title: "Apply changes to the Agent?",
              description:
                "This saves the changes while keeping the Agent stopped. Start it from the Agent detail page when you are ready.",
            }
      }
    />
  );
}
