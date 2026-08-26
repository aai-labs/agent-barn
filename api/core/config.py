from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import PostgresDsn
from pydantic_settings import BaseSettings

ROOT_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(ROOT_ENV_PATH, override=False)


class Config(BaseSettings):
    db_connection_url: PostgresDsn
    secret_signing_key: str
    platform_admin_credentials: str
    platform_admin_full_name: str = "Super User"
    # Cloudflare Email Sending. The token needs the "Email Sending: Edit" permission and
    # must belong to the account identified by cloudflare_account_id.
    cloudflare_account_id: str | None = None
    cloudflare_api_token: str | None = None
    # Visible "From" address, e.g. noreply@mail.agentbarn.dev. Its domain MUST be onboarded
    # and Verified for Email Sending in that account or Cloudflare rejects the send.
    # Each environment sends from its own `mail.`-style subdomain so a damaged sending
    # reputation can't reach the root domain (website, logins) or another environment.
    sender_email: str | None = None
    email_from_name: str = "Agent Barn"

    environment: str = "local"
    web_app_url: str = "http://localhost:3000"
    access_token_expire_minutes: int | None = None
    refresh_token_expire_days: int | None = None

    k8s_kubeconfig_path: str | None = None
    k8s_namespace: str = "agent-farm"
    # StorageClass for PVCs the API provisions (agent pods). Empty falls through
    # to the cluster's default StorageClass.
    storage_class: str = ""

    openclaw_image: str = ""
    hermes_image: str = ""
    agent_token_encryption_key: str = ""
    litellm_api_key: str = ""
    litellm_base_url: str = ""
    litellm_secret_name: str = "litellm"
    agent_litellm_base_url: str = ""
    agent_image_pull_secret: str = ""
    agent_default_model: str = "litellm/openrouter/z-ai/glm-5.2"
    organization_creation_limit: int = 5
    api_external_url: str = ""
    # Agent workloads and the API run in the same namespace, so the short Service
    # name is portable between staging and production.
    ingest_base_url: str = "http://agentbarn-api:8001/ingest/v1"
    communications_base_url: str = (
        "http://agentbarn-api-communications.agent-farm.svc.cluster.local:8002/communications/v1"
    )
    skip_slack_token_validation: bool = False
    skip_telegram_token_validation: bool = False
    skip_discord_token_validation: bool = False
    slack_directory_cache_ttl_seconds: int = 600
    # Socket timeout for Slack Web API calls. Large sweeps (e.g. users.list can be
    # ~320KB) are slow over a poor link; too tight a timeout cuts the body off
    # mid-stream (IncompleteRead). Generous default; in-cluster latency is low.
    slack_request_timeout_seconds: int = 30

    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_models_cache_ttl_seconds: int = 3600
    # TTL for the credits poll behind agentbarn_openrouter_credits_remaining
    # (GET /key with the inference key above; no management key involved).
    openrouter_credits_cache_ttl_seconds: int = 300

    redis_url: str = "redis://localhost:6379/0"

    # Comma-separated glob patterns (fnmatch) matched against OpenRouter model
    # ids to limit what the model picker offers, e.g. "z-ai/glm-5.2,openai/gpt-5*".
    # Empty allows the full catalogue.
    agent_model_allowlist: str = ""

    # Shared Google OAuth 2.0 "Web application" client used by the "Authenticate
    # with Google" flow when a user connects the Gmail skill. The refresh token is
    # minted per-agent; these app-owned credentials are never shown to users and are
    # injected into the agent's aai-cli gmail-work profile at start time.
    google_cloud_client_id: str = ""
    google_cloud_client_secret: str = ""

    agent_firecrawl_base_url: str = ""
    agent_firecrawl_api_key: str = ""

    @property
    def is_email_delivery_enabled(self) -> bool:
        return bool(
            (self.cloudflare_account_id or "").strip()
            and (self.cloudflare_api_token or "").strip()
            and (self.sender_email or "").strip()
        )


@lru_cache
def get_config() -> Config:
    config = Config()
    return config
