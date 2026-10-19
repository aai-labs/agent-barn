# Organization storage sync is a provider seam, one connection at a time

Status: Accepted
Date: 2026-10-16
Origin: AF-383, decided with the maintainer during implementation; follows the Platform Plugin boundary in Communications

Connecting an Organization to storage is a generic sync provider with one plugin per provider, and OneDrive is the first plugin. The maintainer's reason: Dropbox and Google Drive will be added, and adding them should be simple. An Organization connects one provider at a time, built so that allowing several later is a small change.

## Decision

- **Provider seam.** `SyncProviderPlugin` and the code-owned `SyncProviderPluginRegistry` live under `api/domains/sync_provider/plugins/` and are registered in `AppModule`, like Platform Plugins.
  - A plugin talks only to its provider. It depends only on that provider's HTTP clients, never on another domain's services or repositories, and never touches the database. OneDrive reuses the Microsoft identity and Graph clients in `api/domains/agents/`, which it shares with the SharePoint integration.
  - A check another domain owns is named by a typed `SyncLocationGuard` and bound in the service, as `TokenBrokerService` is for Integration Plugins.
  - The table (`sync_provider_connection`), the routes (`…/sync-providers/{provider_key}/…`) and the Sync settings UI are generic, and provider wording comes from the plugin's descriptor.
- **One connection at a time.** This rule lives only in `SyncProviderService._blocking_connection` and the partial unique index on `organization_id`. Everything else is keyed by provider.

## Consequences

- A new provider is a plugin, its provider client and tests. It needs no route, table, migration or UI branch. The steps are in [Sync providers](../features/sync-provider/README.md#adding-a-provider).
- Allowing several providers at once means removing one check, changing the index to `(organization_id, provider_key)` in a migration, and rewriting one test group in each of two files.
- Microsoft-specific behaviour stays in the OneDrive plugin: the Entra app, the SharePoint site grant, and the guard keeping Agents off the folder site.
