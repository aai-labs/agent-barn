# TOOLS.md - Integration Notes for {{ agent_display_name }}

## Email

Email is accessed exclusively through the CLI for the configured platform — do not attempt himalaya, mutt, curl, or any other tool.

Read `email_platform` from USER.md, then use the matching tool:

| `email_platform` | Tool | Reference |
|---|---|---|
| `google_workspace` | `gog gmail` (no `--profile`) | the Google Workspace block in AGENTS.md |
| `zoho_mail` | `aai-cli email --profile zoho-mail-rest` | `./skills/aai-cli/zoho_mail_skill.md` |

The two are different tools with different grammars: `gog` is already authenticated as the
user's Google account and takes no profile flag, while `aai-cli` requires `--profile`. Do
not pass `--profile` to `gog`, and do not use `aai-cli email` for Google.

**Google Workspace (`google_workspace`)**

List new emails, then read one:
```
gog gmail search 'newer_than:1d'
gog gmail messages get <MESSAGE_ID>
```

**Zoho Mail (`zoho_mail`)**

Read `./skills/aai-cli/zoho_mail_skill.md` first — it documents the exact subcommands,
flags, and response shapes.
```
aai-cli email messages list --received-after <YYYY-MM-DD> --profile zoho-mail-rest
aai-cli email messages get <MESSAGE_ID> --profile zoho-mail-rest
```

## Slack

Use the built-in Slack integration to post to `slack_notification_channel` from USER.md. Do not DM individuals unless the configured channel is itself a DM.
