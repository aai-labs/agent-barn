# TOOLS.md - Integration Notes for {{ agent_display_name }}

## Email

Email is accessed exclusively through the `gog` CLI — do not attempt himalaya, mutt, curl, or any other tool.

`gog` is already authenticated as the user's Google account and takes no `--profile` flag.

List new emails, then read one:
```
gog gmail search 'newer_than:1d'
gog gmail messages get <MESSAGE_ID>
```

## Slack

Use the built-in Slack integration to post to `slack_notification_channel` from USER.md. Do not DM individuals unless the configured channel is itself a DM.
