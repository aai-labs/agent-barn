# Credential isolation is an optional per-Agent integration choice

Status: Accepted
Date: 2026-10-08
Origin: Maintainer direction in the credential-gateway branch review
Partly supersedes: [Permanent provider routing](2026-09-02-credential-gateway-egress-modes.md)

The maintainer requested isolation that is optional and off by default so users can turn it off if gateway routing breaks. The setting belongs to an Agent's integration binding, independently of the reusable credential. A provider catalogue declares supported routes and provider-specific descriptions alongside runtime plugins; a common resolver combines those capabilities with the user's choice. OFF materializes the required credentials into the runtime. ON proxies tool requests, or supplies short-lived Google and Microsoft Graph access tokens while keeping renewable credentials service-side. Native messaging transports retain their runtime credentials.

This revises the earlier decision's permanent per-provider routing, not its proxy/broker boundary, trusted plugin model or unrestricted internet access. Applying either direction to a running Agent requires an explicit restart and preserves usable credentials. Failures never silently turn isolation off. Shared UI descriptions must describe the selected provider, rather than generalizing Google's broker behavior to other integrations.

Implementation preserves legacy routes through migration and defaults new bindings OFF. Explicit generation tracking distinguishes desired policy from a verified runtime; failed application retains intent without fallback and offers explicit retry or restoration of the last verified mode. Platform-default Firecrawl has an independent source choice so a stored override cannot erase it. SharePoint transitions prove and persist the last direct-pod rotation before deleting it, then hand back the latest service-side grant when direct mode is selected. These mechanisms implement the maintainer's credential-continuity and recovery requirements; [current contracts](../features/integrations.md#optional-credential-isolation) own their detailed behavior.
