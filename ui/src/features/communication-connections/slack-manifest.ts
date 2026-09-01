/** Static sample pasted into Slack's "From Manifest" flow; it is not an API contract. */
export const SLACK_APP_MANIFEST = {
  display_information: {
    name: "Agent Barn",
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
        "channels:history", "channels:read", "chat:write", "groups:history", "groups:read",
        "im:history", "im:read", "mpim:history", "mpim:read", "reactions:write", "users:read",
      ],
    },
    pkce_enabled: false,
  },
  settings: {
    event_subscriptions: {
      bot_events: ["message.channels", "message.groups", "message.im", "message.mpim"],
    },
    org_deploy_enabled: true,
    socket_mode_enabled: true,
    token_rotation_enabled: false,
  },
} as const;
