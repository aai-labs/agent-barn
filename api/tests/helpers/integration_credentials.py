"""Deterministic, non-live credentials for runtime adapter contracts."""

from api.domains.agents.models import SecretContent, SecretProvider, validate_content


def credential_for(provider: SecretProvider) -> SecretContent:
    payloads = {
        SecretProvider.GITHUB: {
            "token": "github-provider-secret",
            "owner": "acme",
            "org": "acme",
            "repos": ["one", "two"],
        },
        SecretProvider.JIRA: {
            "site_url": "https://acme.atlassian.net",
            "email": "fixture@example.com",
            "api_token": "jira-provider-secret",
        },
        SecretProvider.CONFLUENCE: {
            "site_url": "https://acme.atlassian.net",
            "email": "fixture@example.com",
            "api_token": "confluence-provider-secret",
        },
        SecretProvider.BITBUCKET: {
            "workspace": "acme",
            "repos": ["one", "two"],
            "email": "fixture@example.com",
            "api_token": "bitbucket-provider-secret",
        },
        SecretProvider.PIPEDRIVE: {"domain": "acme", "api_token": "pipedrive-provider-secret"},
        SecretProvider.GOOGLE_WORKSPACE: {
            "email": "fixture@example.com",
            "services": ["gmail"],
            "refresh_token": "google_workspace-provider-secret",
            "client_id": "fixture.apps.googleusercontent.com",
            "client_secret": "google-client-secret",
        },
        SecretProvider.FIRECRAWL: {"api_key": "firecrawl-provider-secret", "base_url": "https://api.firecrawl.dev"},
        SecretProvider.SHAREPOINT: {
            "connection_id": "33333333-3333-4333-8333-333333333333",
            "tenant_id": "22222222-2222-4222-8222-222222222222",
            "client_id": "11111111-1111-4111-8111-111111111111",
            "email": "fixture@example.com",
            "scopes": ["Sites.Read.All"],
            "read_only": True,
            "refresh_token": "sharepoint-provider-secret",
            "sign_in_id": "44444444-4444-4444-8444-444444444444",
        },
    }
    return validate_content(provider, payloads[provider])
