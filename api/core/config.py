from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field, PostgresDsn, field_validator
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
    # Percentages of an Organization's limit at which it is notified. Empty falls back
    # to the default; 100 is always meaningful because it is the enforcement boundary.
    organization_llm_budget_alert_thresholds: str = "80,100"
    api_external_url: str = ""
    # Agent workloads and the API run in the same namespace, so the short Service
    # name is portable between staging and production.
    ingest_base_url: str = "http://agentbarn-api:8001/ingest/v1"
    communications_base_url: str = (
        "http://agentbarn-api-communications.agent-farm.svc.cluster.local:8002/communications/v1"
    )
    # Where the API relays runtime-owned Teams activities. Local Docker/k3d
    # cannot resolve cluster DNS, so compose overrides this with a port-forward.
    teams_runtime_webhook_url: str = "http://agent-{agent_id}.{namespace}.svc.cluster.local:3978/api/messages"
    agent_trigger_url: str = "http://agent-{agent_id}.{namespace}.svc.cluster.local:8082/agent-triggers/v1/invocations"
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

    @field_validator("organization_llm_budget_alert_thresholds", mode="before")
    @classmethod
    def valid_thresholds(cls, value: object) -> object:
        """Validated at construction, not on use: a malformed list should refuse to
        boot rather than silently alert nobody."""
        if not isinstance(value, str) or not value.strip():
            return "80,100"
        try:
            parsed = sorted({int(part.strip()) for part in value.split(",")})
        except ValueError as error:
            raise ValueError("Budget alert thresholds must be whole numbers, comma separated") from error
        if not parsed or parsed[0] < 1 or parsed[-1] > 100:
            raise ValueError("Budget alert thresholds must be between 1 and 100")
        # 100 is the enforcement boundary, not a notification preference. Omitting it
        # would leave an exhausted Organization with a banner saying so and no mail:
        # only the highest crossed threshold fires, and a lower one is already spent.
        if parsed[-1] != 100:
            parsed.append(100)
        return ",".join(str(threshold) for threshold in parsed)

    @property
    def llm_budget_alert_thresholds(self) -> list[int]:
        """Sorted and de-duplicated by the validator above."""
        return [int(part) for part in self.organization_llm_budget_alert_thresholds.split(",")]

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
