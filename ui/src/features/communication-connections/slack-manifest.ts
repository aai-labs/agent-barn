/** Static portion of the copyable Slack sample; this is not an API contract. */
const SLACK_APP_MANIFEST_TEMPLATE = {
  display_information: {
    description: "Connect an Agent Barn agent to Slack.",
  },
  features: {
    app_home: {
      home_tab_enabled: true,
      messages_tab_enabled: false,
      messages_tab_read_only_enabled: true,
    },
    bot_user: {
      display_name: "AgentBarn",
      always_online: true,
    },
  },
  oauth_config: {
    scopes: {
      bot: [
        "app_mentions:read",
        "bookmarks:read",
        "canvases:read",
        "canvases:write",
        "channels:history",
        "channels:join",
        "channels:read",
        "chat:write",
        "chat:write.customize",
        "chat:write.public",
        "emoji:read",
        "files:read",
        "files:write",
        "groups:history",
        "groups:read",
        "im:history",
        "im:read",
        "im:write",
        "mpim:history",
        "mpim:read",
        "mpim:write",
        "pins:read",
        "pins:write",
        "reactions:read",
        "reactions:write",
        "search:read.users",
        "users:read",
        "users:read.email",
      ],
    },
    pkce_enabled: false,
  },
  settings: {
    interactivity: {
      is_enabled: true,
    },
    event_subscriptions: {
      bot_events: [
        "app_mention",
        "channel_rename",
        "member_joined_channel",
        "member_left_channel",
        "message.channels",
        "message.groups",
        "message.im",
        "message.mpim",
        "pin_added",
        "pin_removed",
        "reaction_added",
        "reaction_removed",
      ],
    },
    org_deploy_enabled: true,
    socket_mode_enabled: true,
    token_rotation_enabled: false,
  },
} as const;

/** Slack limits display_information.name to 35 characters. */
const MAX_SLACK_APP_NAME_LENGTH = 35;
/** Slack limits display_information.description to 140 characters. */
const MAX_SLACK_APP_DESCRIPTION_LENGTH = 140;
/** Slack limits features.bot_user.display_name to 80 characters. */
const MAX_SLACK_BOT_DISPLAY_NAME_LENGTH = 80;

export function createSlackAppManifest(rawAgentName: string, agentDescription?: string | null) {
  const agentName = rawAgentName.trim();
  const agentNameCharacters = Array.from(agentName);
  const appName = agentNameCharacters.slice(0, MAX_SLACK_APP_NAME_LENGTH).join("").trim();
  const description = Array.from(
    agentDescription?.trim() || SLACK_APP_MANIFEST_TEMPLATE.display_information.description,
  ).slice(0, MAX_SLACK_APP_DESCRIPTION_LENGTH).join("").trim();
  const normalizedBotName = agentName
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/^-+|-+$/g, "");
  // Give names without an ASCII slug a stable, Slack-safe label.
  const encodedAgentName = agentNameCharacters
    .map((character) => character.codePointAt(0)!.toString(16))
    .join("-");
  const botDisplayName = (
    normalizedBotName || (encodedAgentName ? `agent-${encodedAgentName}` : "agent")
  ).slice(0, MAX_SLACK_BOT_DISPLAY_NAME_LENGTH);

  return {
    ...SLACK_APP_MANIFEST_TEMPLATE,
    display_information: {
      name: appName,
      description,
    },
    features: {
      ...SLACK_APP_MANIFEST_TEMPLATE.features,
      bot_user: {
        ...SLACK_APP_MANIFEST_TEMPLATE.features.bot_user,
        display_name: botDisplayName,
      },
    },
  } as const;
}
