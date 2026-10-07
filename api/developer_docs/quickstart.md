# API quickstart

AgentBarn exposes its product API at `/api/v1`. Create a personal API key in **Account → API keys**, then send it as `Authorization: Bearer abk_...`. A key acts as its user across current Organization Memberships. Read-only keys can make read requests; full-access keys can also make changes, subject to the user's current permissions.

```bash
export AGENTBARN_URL='https://your-agentbarn-host'
export AGENTBARN_KEY='abk_...'
curl -sS "$AGENTBARN_URL/api/v1/auth/context" \
  -H "Authorization: Bearer $AGENTBARN_KEY"
```

The context response contains your `user_id`, `organizations` with UUIDs and roles, `is_platform_admin`, and the key's access mode. Choose an Organization ID from that response:

```bash
export ORGANIZATION_ID='your-organization-uuid'
curl -sS "$AGENTBARN_URL/api/v1/organizations/$ORGANIZATION_ID/agents?page=1&page_size=15" \
  -H "Authorization: Bearer $AGENTBARN_KEY"
```

The Agent list contains only Agents visible under your current Agent Access. Use `GET /api/v1/organizations/{organization_id}/agents/{agent_id}` for details. The [OpenAPI schema](/api/v1/openapi.json) lists every endpoint, parameter, and response; the [interactive reference](/api/v1/docs) lets you explore them. [Operation discovery](/api/v1/discovery) provides a compact catalog.
