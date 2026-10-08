# aai-cli Apollo Skill

Agent reference for the `aai-cli apollo` command group.
                                                
## Global flags

Accepted by every command. Can also be set via environment variables.

| Flag | Env | Default | Description |
|---|---|---|---|
| `--profile NAME` | `AAI_PROFILE` | config `default_profile` | Profile from `~/.config/aai-cli/config.toml` |
| `--config PATH` | `AAI_CONFIG` | `~/.config/aai-cli/config.toml` | Path to config file |
| `--secrets-file PATH` | `AAI_SECRETS_FILE` | `~/.config/aai-cli/secrets.enc.json` | Path to encrypted secrets file |
| `--key-file PATH` | `AAI_SECRET_KEY_FILE` | `/run/aai/key` or `~/.config/aai-cli/key` | Path to decryption key file |

## Profile

Apollo profiles use API-key auth:

```toml
[profiles.apollo-work]
provider = "apollo"
auth_type = "apollo_api_key"
api_token_secret = "apollo.api_token"
# Optional; defaults to https://api.apollo.io/api/v1
base_url = "https://api.apollo.io/api/v1"
```

Apollo's documented API-key health check is outside the main `/api/v1` base and is exposed as `apollo health`. Generic `apollo request` paths remain relative to `profile.base_url`.

## Response shapes

Successful command output is JSON on stdout.

Apollo responses preserve the provider's response shape where possible. List and search commands aggregate provider pagination up to `--limit` and add this CLI's `_aai.pagination` metadata when pagination handling is available:

```json
{
  "_aai": {
    "pagination": {
      "continuation": null,
      "has_more": false,
      "instruction": "...",
      "next_command": null,
      "returned_count": 25,
      "status": "complete"
    }
  },
  "...": "rest of the provider response"
}
```

Apollo uses different top-level array keys by endpoint, such as `people`, `organizations`, `contacts`, `accounts`, `opportunities`, `tasks`, `phone_calls`, `notes`, `emailer_campaigns`, `news_articles`, `conversations`, `users`, and `job_postings`.

For outreach email search, Apollo may return an email-specific array such as `emailer_messages`. Confirm the live response shape before relying on large-window email pagination; if the email array is not represented in `_aai.pagination.returned_count`, use narrower date windows or the raw provider totals until the paginator is updated for that array key.

When a report depends on complete totals, compare the returned array count, `_aai.pagination`, and any provider totals in the payload. If results may be capped, rerun with a larger `--limit` or narrower filters.

## Error response shape

All errors print to stderr as a single JSON line:

```json
{
  "code": "provider_api_error",
  "details": { "error": "..." },
  "message": "provider returned HTTP 400",
  "operation": "people.search",
  "service": "apollo",
  "status": 400
}
```

| Code | Meaning |
|---|---|
| `invalid_input` | A required flag was missing or a value was rejected before the API call |
| `config_error` | Missing or malformed config, profile, or token setting |
| `auth_error` | Missing credentials, invalid token, or provider 401/403 |
| `not_found` | Provider returned 404 |
| `rate_limited` | Provider returned 429 |
| `provider_api_error` | Provider returned another 4xx/5xx |
| `internal_error` | Local request, response, or IO failure |

Exit code is non-zero on any error.

## Resources

- [Health and request](#health-and-request) - `health`, `request`
- [People](#people) - `people search`, `get`, `enrich`, `bulk-enrich`
- [Organizations](#organizations) - `organizations search`, `get`, `enrich`, `bulk-enrich`, `job-postings`
- [Contacts](#contacts) - saved Apollo contact records
- [Accounts](#accounts) - saved Apollo account records
- [Deals](#deals) - Apollo opportunities/deals
- [Tasks, calls, and notes](#tasks-calls-and-notes) - outreach and activity records
- [Users and metadata](#users-and-metadata) - users, labels, fields, custom fields, usage, webhooks, analytics
- [Sequences and emails](#sequences-and-emails) - sequence search/management and outreach emails
- [News and conversations](#news-and-conversations) - account signals and conversation intelligence
- [Reporting guidance](#reporting-guidance) - campaign, sourcing, outreach, reply, and handoff metrics

## Health and request

### health

Verify that the Apollo API key authenticates.

```bash
aai-cli apollo health
```

Health does not prove every endpoint or account permission is available.

### request

Use `request` for uncommon Apollo endpoints or filters not exposed by a typed command.

```bash
aai-cli apollo request get <relative-path> [--query key=value ...]
aai-cli apollo request post <relative-path> --allow-write [--json <path|->] [--query key=value ...]
```

Examples:

```bash
aai-cli apollo request get /users/api_profile
aai-cli apollo request post /people/match --allow-write --query email=ada@example.com
```

Prefer typed commands for normal workflows because they preserve this CLI's provider conventions.

## People

People commands are for Apollo's person discovery and enrichment records. Lead search uses Apollo's provider terminology: `people search`.

```bash
aai-cli apollo people search [--limit N] [--q-keywords TEXT] [--title TEXT] [--location TEXT] [--domain DOMAIN] [--query key=value ...]
aai-cli apollo people get <person-id>
aai-cli apollo people enrich [--json <path|->] [--email EMAIL] [--first-name TEXT] [--last-name TEXT] [--name TEXT] [--organization-name TEXT] [--domain DOMAIN] [--id ID] [--linkedin-url URL] [--reveal-personal-emails] [--reveal-phone-number]
aai-cli apollo people bulk-enrich [--json <path|->] [--query key=value ...]
```

Examples:

```bash
aai-cli --profile apollo-work apollo people search --title CEO --location Berlin --limit 10
aai-cli --profile apollo-work apollo people enrich --email ada@example.com
```

Use people search for prospect sourcing. Use contacts commands after a person is saved as an Apollo contact.

The typed `--title` flag sends Apollo's `person_titles[]` parameter. The typed `--location` flag sends both `person_locations[]` and `organization_locations[]`. For precise searches, prefer explicit query parameters such as `--query person_locations[]=Berlin` or `--query organization_locations[]=Berlin`.

## Organizations

Organizations commands are for Apollo company discovery and enrichment records.

```bash
aai-cli apollo organizations search [--limit N] [--q-name TEXT] [--location TEXT] [--domain DOMAIN] [--query key=value ...]
aai-cli apollo organizations get <organization-id>
aai-cli apollo organizations enrich [--domain DOMAIN] [--linkedin-url URL] [--name TEXT] [--website URL]
aai-cli apollo organizations bulk-enrich [--json <path|->] [--query key=value ...]
aai-cli apollo organizations job-postings <organization-id> [--limit N] [--query key=value ...]
```

Examples:

```bash
aai-cli --profile apollo-work apollo organizations search --q-name "manufacturing" --location "United States" --limit 25
aai-cli --profile apollo-work apollo organizations enrich --domain example.com
```

Use organizations for company sourcing. Use accounts commands after a company is saved as an Apollo account.

The typed `--domain` flag sends Apollo's `q_organization_domains_list[]` parameter. The typed `--location` flag sends both `person_locations[]` and `organization_locations[]`; organization search ignores irrelevant person filters, but explicit `--query organization_locations[]=...` is clearer for reporting and repeatable sourcing.

## Contacts

Contacts are saved Apollo people records.

```bash
aai-cli apollo contacts create [--json <path|->] [--first-name TEXT] [--last-name TEXT] [--organization-name TEXT] [--email EMAIL] [--account-id ID] [--title TEXT] [--website-url URL] [--contact-stage-id ID]
aai-cli apollo contacts get <contact-id>
aai-cli apollo contacts search [--json <path|->] [--limit N] [--q-keywords TEXT] [--sort-by-field FIELD] [--sort-ascending true|false]
aai-cli apollo contacts update <contact-id> [--json <path|->] [--first-name TEXT] [--last-name TEXT] [--organization-name TEXT] [--email EMAIL] [--account-id ID] [--title TEXT] [--website-url URL] [--contact-stage-id ID]
aai-cli apollo contacts bulk-create [--json <path|->]
aai-cli apollo contacts bulk-update [--json <path|->]
aai-cli apollo contacts update-stages --ids CSV --stage-id ID
aai-cli apollo contacts update-owners --ids CSV --owner-id ID
aai-cli apollo contacts deals <contact-id> [--json <path|->]
```

Examples:

```bash
aai-cli --profile apollo-work apollo contacts search --q-keywords "vp sales" --limit 25
aai-cli --profile apollo-work apollo contacts create --email ada@example.com --first-name Ada --last-name Lovelace
```

For commands that accept `--json`, typed flags override matching top-level JSON fields.

## Accounts

Accounts are saved Apollo company records.

```bash
aai-cli apollo accounts create [--json <path|->] [--name TEXT] [--domain DOMAIN] [--owner-id ID] [--account-stage-id ID] [--phone TEXT] [--raw-address TEXT]
aai-cli apollo accounts get <account-id>
aai-cli apollo accounts search [--json <path|->] [--limit N] [--q-name TEXT] [--sort-by-field FIELD] [--sort-ascending true|false]
aai-cli apollo accounts update <account-id> [--json <path|->] [--name TEXT] [--domain DOMAIN] [--owner-id ID] [--account-stage-id ID] [--phone TEXT] [--raw-address TEXT]
aai-cli apollo accounts bulk-create [--json <path|->]
aai-cli apollo accounts bulk-update [--json <path|->]
aai-cli apollo accounts update-owners --ids CSV --owner-id ID
aai-cli apollo accounts stages
```

Examples:

```bash
aai-cli --profile apollo-work apollo accounts search --q-name "Acme" --limit 10
aai-cli --profile apollo-work apollo accounts stages
```

## Deals

Apollo deal commands map to Apollo opportunity/deal resources.

```bash
aai-cli apollo deals create [--json <path|->] [--name TEXT] [--owner-id ID] [--account-id ID] [--amount NUM] [--opportunity-stage-id ID] [--closed-date DATE]
aai-cli apollo deals list [--limit N] [--sort-by-field FIELD]
aai-cli apollo deals get <deal-id>
aai-cli apollo deals update <deal-id> [--json <path|->] [--name TEXT] [--owner-id ID] [--account-id ID] [--amount NUM] [--opportunity-stage-id ID] [--closed-date DATE]
aai-cli apollo deals stages
```

Examples:

```bash
aai-cli --profile apollo-work apollo deals list --limit 25
aai-cli --profile apollo-work apollo deals stages
```

## Tasks, calls, and notes

Tasks and calls can support outreach activity reporting, but validate live payload fields before treating created/completed counts as final.

```bash
aai-cli apollo tasks create [--json <path|->] [--user-id ID] [--contact-id ID] [--type TYPE] [--priority PRIORITY] [--status STATUS] [--due-at TS] [--title TEXT] [--note TEXT]
aai-cli apollo tasks bulk-create [--json <path|->]
aai-cli apollo tasks search [--limit N] [--query key=value ...]

aai-cli apollo calls create [--query key=value ...] [--contact-id ID] [--account-id ID] [--to-number NUMBER] [--from-number NUMBER] [--status STATUS] [--start-time TS] [--end-time TS] [--duration SECONDS] [--note TEXT]
aai-cli apollo calls search [--limit N] [--q-keywords TEXT] [--query key=value ...]
aai-cli apollo calls update <call-id> [--query key=value ...] [--contact-id ID] [--account-id ID] [--to-number NUMBER] [--from-number NUMBER] [--status STATUS] [--start-time TS] [--end-time TS] [--duration SECONDS] [--note TEXT]

aai-cli apollo notes list [--limit N] [--contact-id ID] [--account-id ID] [--opportunity-id ID] [--start-date DATE] [--sort-by-field FIELD] [--sort-direction asc|desc]
```

Examples:

```bash
aai-cli --profile apollo-work apollo tasks search --limit 10
aai-cli --profile apollo-work apollo calls search --limit 10
aai-cli --profile apollo-work apollo notes list --contact-id <contact-id> --limit 50
```

Do not infer completed LinkedIn messages or completed calls from task existence alone. Check whether the returned payload includes reliable task type, status, owner, and completion timestamp fields.

## Users and metadata

```bash
aai-cli apollo users list [--limit N]
aai-cli apollo users me [--include-credit-usage]
aai-cli apollo labels list
aai-cli apollo fields list [--source SOURCE]
aai-cli apollo fields create [--json <path|->] [--label TEXT] [--modality TEXT] [--type TYPE]
aai-cli apollo custom-fields list
aai-cli apollo usage stats
aai-cli apollo webhooks result <request-id>
aai-cli apollo analytics report [--json <path|->]
```

Examples:

```bash
aai-cli --profile apollo-work apollo users me --include-credit-usage
aai-cli --profile apollo-work apollo custom-fields list
aai-cli --profile apollo-work apollo usage stats
```

Apollo custom fields are available for supported object types such as contacts, accounts, and opportunities. Do not assume sequence custom fields exist. If a workflow needs sequence-to-campaign mapping, keep that mapping in a separate source of truth unless the Apollo account schema proves otherwise.

## Sequences and emails

Sequences:

```bash
aai-cli apollo sequences search [--limit N] [--q-name TEXT]
aai-cli apollo sequences create [--json <path|->] [--name TEXT] [--active true|false] [--user-id ID]
aai-cli apollo sequences update <sequence-id> [--json <path|->] [--name TEXT] [--active true|false] [--user-id ID]
aai-cli apollo sequences add-contacts <sequence-id> --contact-ids CSV [--status STATUS] [--email-account-id ID] [--email-address EMAIL]
aai-cli apollo sequences update-contact-status --sequence-ids CSV --contact-ids CSV --mode MODE
aai-cli apollo sequences activate <sequence-id>
aai-cli apollo sequences deactivate <sequence-id>
aai-cli apollo sequences archive <sequence-id>
```

Emails:

```bash
aai-cli apollo emails draft [--json <path|->] [--contact-id ID] [--subject TEXT] [--body-html HTML]
aai-cli apollo emails send-now <message-id> [--json <path|->] [--surface TEXT]
aai-cli apollo emails send-status [--json <path|->]
aai-cli apollo emails search [--limit N] [--q-keywords TEXT] [--query key=value ...]
aai-cli apollo emails stats <message-id>
aai-cli apollo emails accounts
```

Examples:

```bash
aai-cli --profile apollo-work apollo sequences search --q-name "September outbound" --limit 25
aai-cli --profile apollo-work apollo emails search --query emailer_campaign_ids[]=<sequence-id> --query emailer_message_date_range_mode=completed_at --query emailer_message_date_range[min]=2026-09-01 --query emailer_message_date_range[max]=2026-09-30 --limit 1000
```

Use `completed_at` when the metric is about sent or completed outreach during a reporting period. Use `due_at` when the metric is about scheduled outreach.

Apollo email status filters use the `emailer_message_stats[]` query parameter. Documented values include:

```text
delivered
scheduled
drafted
not_opened
opened
clicked
unsubscribed
demoed
bounced
spam_blocked
failed_other
```

Apollo email reply-class filters use the `emailer_message_reply_classes[]` query parameter. Documented values include:

```text
willing_to_meet
follow_up_question
person_referral
out_of_office
already_left_company_or_not_right_person
not_interested
unsubscribe
none_of_the_above
```

Confirm the exact returned values from live data before reporting final status or reply-class totals.

## News and conversations

```bash
aai-cli apollo news search [--limit N] [--query key=value ...]

aai-cli apollo conversations search [--json <path|->] [--limit N] [--conversation-type TYPE] [--account-id ID]
aai-cli apollo conversations get <conversation-id>
aai-cli apollo conversations export [--json <path|->]
aai-cli apollo conversations get-export <export-id>
```

Examples:

```bash
aai-cli --profile apollo-work apollo news search --limit 25
aai-cli --profile apollo-work apollo conversations search --conversation-type call --limit 25
```

Use news and job-posting commands for account or market signals. Use conversations commands only when the Apollo account has conversation intelligence data available.

## JSON and query inputs

For every Apollo command that accepts `--json`, typed flags override matching top-level JSON fields.

Use repeated `--query key=value` for Apollo parameters that do not have first-class flags:

```bash
aai-cli apollo emails search --query emailer_campaign_ids[]=123 --query emailer_message_date_range_mode=completed_at
```

Some Apollo commands use query parameters and some use JSON request bodies. Prefer documented typed flags first, then use `--query` or `--json` according to the command help.

## Reporting guidance

Apollo should be treated as the activity source for Apollo-sourced prospects and Apollo-run outreach. It should not be treated as the only source of truth for CRM pipeline when Pipedrive is also in the workflow.

### Campaign mapping

Keep a campaign mapping table before calculating campaign metrics.

Minimum useful fields:

```text
campaign_name
apollo_sequence_id
jira_campaign_key
pipedrive_campaign_label_or_field
owner
start_date
end_date
notes
```

Do not assume Apollo sequences, Jira campaigns, and Pipedrive labels have identical names. Resolve the mapping first, then report from the mapped IDs.

### Sourcing metrics

Sourcing metrics usually come from people and organization searches or saved contacts/accounts.

Use organizations/accounts for company counts and people/contacts for person counts. Do not mix those counts without naming the object type.

Recommended labels:

```text
Sourced companies: Apollo organizations found for the campaign
Saved accounts: Apollo accounts created or matched for the campaign
Sourced people: Apollo people found for the campaign
Saved contacts: Apollo contacts created or matched for the campaign
Enriched records: Apollo people or organizations enriched for the campaign
```

### Outreach and reply metrics

Define reply metrics by event date, not by lifetime contact state, unless the user explicitly asks for lifetime totals.

Recommended reporting fields:

```text
campaign_name
apollo_sequence_id
date_window_start
date_window_end
emails_sent
emails_delivered
emails_opened
emails_clicked
human_replies
positive_replies
negative_replies
referrals
out_of_office
unsubscribes
bounces
```

For Sally-style sales reporting, human replies are usually the handoff point. If respondents are moved into Pipedrive manually, state that the Apollo-to-Pipedrive conversion is manual unless automation has been added.

### Owners

Separate record ownership from activity ownership.

Record owner answers:

```text
Who owns this contact, account, or deal?
```

Activity owner answers:

```text
Who sent the email, completed the task, logged the call, or handled the reply?
```

Use the activity actor for productivity metrics. Use the record owner for account or pipeline responsibility.

### Quality checks

Before delivering Apollo metrics, check:

```text
The sequence ID matches the campaign mapping.
The date filter uses the intended event timestamp.
Returned count and provider total make sense together.
The result is not silently capped by the requested limit.
Reply classes are based on live returned values.
Manual handoff steps are labeled as manual.
Apollo-only and Pipedrive-inclusive metrics are separated.
```

If a metric cannot be proven from Apollo alone, say what Apollo can prove and which external source is needed.
