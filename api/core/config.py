from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field, PostgresDsn
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
    agent_email_domain: str = ""
    agent_email_mailbox: str = "agent"
    email_inbound_secret: str = ""

    environment: str = "local"
    web_app_url: str = "http://localhost:3000"
    access_token_expire_minutes: int | None = None
    refresh_token_expire_days: int | None = None

    k8s_kubeconfig_path: str | None = None
    k8s_namespace: str = "agent-farm"
    # StorageClass for PVCs the API provisions (agent pods). Empty falls through
    # to the cluster's default StorageClass.
    storage_class: str = ""

    api_image: str = ""
    restore_point_size: str = "1Gi"
    restore_point_max_per_agent: int = Field(default=5, ge=1, le=50)
    restore_point_capture_timeout_seconds: int = Field(default=900, ge=60, le=7200)
    restore_point_restore_timeout_seconds: int = Field(default=1800, ge=60, le=7200)

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
    skip_teams_token_validation: bool = False
    # Shown to Teams administrators reviewing a generated app package. Must be
    # publicly reachable or Teams rejects the upload.
    teams_publisher_name: str = "Agent Barn"
    teams_publisher_website_url: str = "https://agentbarn.dev"
    teams_privacy_url: str = "https://aai-labs.com/privacy"
    teams_terms_url: str = "https://aai-labs.com/terms"
    slack_directory_cache_ttl_seconds: int = 600
    # Content-free Communication journal history is pruned by the gateway
    # supervisor after this many days.
    communication_journal_retention_days: int = Field(default=31, ge=1, le=3650)
    # Webhook events wait in the queue while their agent is stopped or busy. Chat deliveries
    # keep a fixed 5 attempts and are not limited by any of these.
    # Per webhook connection: past this many waiting events, the oldest is dead-lettered.
    communications_event_backlog_cap: int = Field(default=100, ge=1, le=10_000)
    # Per agent: event runs going at once. At the cap, further events stay queued.
    communications_max_in_flight_event_runs_per_agent: int = Field(default=3, ge=1, le=50)
    # Attempts for an event whose run reported a failure. 1 makes that failure final.
    communications_event_max_attempts_after_failure: int = Field(default=1, ge=1, le=10)
    # Attempts for an event whose claim lease expired (pod restart, node loss).
    communications_event_max_attempts_after_lease_expiry: int = Field(default=2, ge=1, le=10)
    # Native gateway spike (ADR 2026-09-16): comma-separated Platform keys whose
    # Connections run inside the Agent runtime's own gateway instead of the
    # Communications supervisor, for Hermes and OpenClaw alike. Replaced by a
    # per-Connection transport once the spike is accepted.
    communications_native_platforms: str = ""

    @property
    def native_platform_keys(self) -> frozenset[str]:
        """Platforms whose Agent Connections run in the runtime's native gateway."""
        return frozenset(key.strip() for key in self.communications_native_platforms.split(",") if key.strip())

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

    @property
    def is_agent_email_enabled(self) -> bool:
        return bool(
            self.is_email_delivery_enabled
            and self.agent_email_domain.strip()
            and self.agent_email_mailbox.strip()
            and self.email_inbound_secret.strip()
        )


@lru_cache
def get_config() -> Config:
    config = Config()
    return config
