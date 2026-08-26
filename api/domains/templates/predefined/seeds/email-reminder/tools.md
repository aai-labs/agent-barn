# TOOLS.md - Integration Notes for {{ agent_display_name }}

## Email

Email is accessed exclusively via **`aai-cli email`**. This is the only email tool available on this agent — do not attempt himalaya, mutt, curl, or any other tool.

Read `email_platform` from USER.md, then choose the correct profile:

| `email_platform` | `--profile` flag | Skill reference |
|---|---|---|
| `gmail` | `--profile gmail-work` | `./skills/aai-gmail/SKILL.md` |
| `zoho_mail` | `--profile zoho-mail-rest` | `./skills/aai-zoho-mail/SKILL.md` |

Always read the skill file before running commands — it documents the exact subcommands, flags, and response shapes for the platform.

**List new emails:**
```
aai-cli email messages list --received-after <YYYY-MM-DD> --profile <profile>
```

**Read a single email:**
```
aai-cli email messages get <MESSAGE_ID> --profile <profile>
```

## Slack

Use the built-in Slack integration to post to `slack_notification_channel` from USER.md. Do not DM individuals unless the configured channel is itself a DM.
