# aai-cli HubSpot Skill

Agent reference for the `aai-cli hubspot` command group.

## Profile

```toml
[profiles.hubspot-work]
provider = "hubspot"
auth_type = "hubspot_service_key" # or "hubspot_legacy_private_app"
token_secret = "hubspot.token"
```

## Common Commands

```bash
aai-cli hubspot health
aai-cli hubspot crm contacts list --limit 25
aai-cli hubspot crm companies get <id> --properties name,domain
aai-cli hubspot crm deals search --json query.json --limit 25
aai-cli hubspot files get <id> --hidden-or-deleted
aai-cli hubspot events occurrences list <event-type> --limit 25
aai-cli hubspot events custom send --json event.json
aai-cli hubspot conversations inboxes list
aai-cli hubspot conversations threads get <id>
aai-cli hubspot conversations visitor-identification tokens create --json token.json
aai-cli hubspot conversations custom-channels list
aai-cli hubspot request get /crm/v3/objects/contacts
```

## Scope Hints

- CRM objects: matching object scopes such as `crm.objects.contacts.read`, `crm.objects.companies.read`, `crm.objects.deals.read`, and `crm.objects.tickets.read`.
- Files: `files`; hidden/deleted reads may also need `files.ui_hidden.read`.
- Event occurrence reads: `business-intelligence`.
- Custom behavioral event sends: `analytics.behavioral_events.send`.
- Conversations reads: `conversations.read`; write flows usually also need `conversations.write`.
- Custom channels: `conversations.custom_channels.read` and `conversations.custom_channels.write`.
- Visitor identification tokens: `conversations.visitor_identification.tokens.create`.

## Error Handling

HubSpot auth failures preserve the provider response under `details.provider` and add `details.auth_type`, `details.endpoint`, `details.required_scopes`, and `details.remediation`.

Custom channel endpoints are not supported for legacy private app tokens. Use a supported HubSpot auth model for those commands.

## Pagination

List and search commands follow HubSpot's `paging.next.after` cursor and aggregate pages up to `--limit`, preserving the provider `results`/`paging` response shape. Use `--after` (or `after` in a search JSON body) to resume from a cursor. The `_aai.pagination` metadata reports remaining continuation and a suggested `next_command`.
