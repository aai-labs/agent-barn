import type { WebhookDeliveryPlatform, WebhookDeliveryPlatformRead } from "./schemas";

export const PLATFORM_LABEL: Record<WebhookDeliveryPlatform, string> = {
  slack: "Slack",
  discord: "Discord",
  telegram: "Telegram",
  teams: "Microsoft Teams",
};

export function deliveryPlatformOptionLabel({ key, displayName }: WebhookDeliveryPlatformRead): string {
  const platformLabel = PLATFORM_LABEL[key];
  const connectionLabel = displayName.trim();

  return connectionLabel.toLowerCase() === platformLabel.toLowerCase()
    ? platformLabel
    : `${platformLabel} · ${connectionLabel}`;
}
