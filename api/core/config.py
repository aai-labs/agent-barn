import ipaddress
from functools import lru_cache
from pathlib import Path
from typing import Self
from urllib.parse import urlparse

from dotenv import load_dotenv
from pydantic import Field, PostgresDsn, field_validator, model_validator
from pydantic_settings import BaseSettings

ROOT_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(ROOT_ENV_PATH, override=False)

DEFAULT_POSTHOG_PROJECT_TOKEN = "phc_AjhfVLSegE5yXsARYYJsGJDC3bwBPdKfUD3dLvoLjbw7"
DEFAULT_POSTHOG_HOST = "https://eu.i.posthog.com"
LOCAL_HOSTNAMES = frozenset({"localhost"})
LOCAL_HOST_SUFFIXES = (".localhost",)
URL_SCHEME_SEPARATOR = "://"


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
    # How long a managed update waits for the new pod to report ready before it
    # rolls back, counted from when the start returns. It has to cover pulling
    # an image the node has never seen, init, the start script's installs, and
    # the probe's 30s initial delay. The readiness probe sets no upper bound of
    # its own: failures only mark the pod unready and probing goes on.
    agent_update_ready_timeout_seconds: int = Field(default=600, ge=30, le=3600)
    agent_update_ready_poll_seconds: int = Field(default=5, ge=0, le=60)

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
    # Model spend limits (USD) a new Organization and a new Agent start with. Required:
    # nobody should be uncapped just because an administrator has not got to them yet.
    # A platform administrator changes an Organization's afterwards; the Organization
    # divides its own allowance among its Agents.
    organization_default_llm_budget_usd: float = Field(ge=0, allow_inf_nan=False)
    agent_default_llm_budget_usd: float = Field(ge=0, allow_inf_nan=False)
    # The API's own public base URL, used to show callers where to reach an Agent
    # Webhook or a Teams Connection. Deployments set it from API_HOST; locally it is
    # derived below, because the host port is the only thing that makes it up.
    api_external_url: str = ""
    # Host-side port the API is published on (compose maps it to 8000 in-container).
    api_port: int = 8000
    # Agent workloads and the API run in the same namespace, so the short Service
    # name is portable between staging and production.
    ingest_base_url: str = "http://agentbarn-api:8001/ingest/v1"
    memory_base_url: str = "http://agentbarn-api-memory:8003/memory/v1"
    # Where the product API reaches the gateway's read-only viewer; Agents never use it.
    memory_view_base_url: str = "http://agentbarn-api-memory:8003/memory/view/v1"
    # Non-secret SHA-256 hashes of current and retired Hindsight LiteLLM keys.
    memory_litellm_key_hashes: str = ""

    memory_runtime_service_key: str = ""

    memory_default_model: str = "openrouter/openai/gpt-4.1-mini"
    memory_litellm_active_key_hash: str = ""

    hindsight_base_url: str = ""
    hindsight_api_key: str = ""
    hindsight_request_timeout_seconds: int = Field(default=120, ge=1, le=600)
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
    # Content-free Communication journal history is pruned by Communications
    # maintenance after this many days.
    communication_journal_retention_days: int = Field(default=31, ge=1, le=3650)
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

    # The in-namespace Prometheus (helm/monitoring) that stores each Agent's CPU and
    # memory. Empty means resource usage reports "not configured", which is the normal
    # local state until `make dev-monitoring`. Prometheus requires basic auth; the
    # password is the monitoring release's MONITORING_WEB_PASSWORD.
    prometheus_url: str = ""
    prometheus_username: str = "monitoring"
    prometheus_password: str = ""
    prometheus_timeout_seconds: float = Field(default=5, gt=0, le=30)

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

    analytics_enabled: bool = True
    analytics_posthog_host: str = DEFAULT_POSTHOG_HOST
    analytics_posthog_project_token: str = DEFAULT_POSTHOG_PROJECT_TOKEN

    @field_validator("analytics_enabled", mode="before")
    @classmethod
    def blank_switch_is_off(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return False
        return value

    @property
    def is_analytics_enabled(self) -> bool:
        return self.analytics_enabled and bool(self.analytics_posthog_project_token.strip())

    @property
    def web_app_host(self) -> str:
        url = self.web_app_url.strip()
        if URL_SCHEME_SEPARATOR not in url:
            url = f"//{url}"
        try:
            host = urlparse(url).hostname or ""
        except ValueError:
            return ""
        return host.rstrip(".").lower()

    @property
    def is_local_installation(self) -> bool:
        host = self.web_app_host
        if not host or host in LOCAL_HOSTNAMES or host.endswith(LOCAL_HOST_SUFFIXES):
            return True
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return False
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        return address.is_loopback or address.is_unspecified

    @model_validator(mode="after")
    def local_api_external_url(self) -> Self:
        """Fill the API's public URL for local runs, where it is always this host.

        Left empty elsewhere on purpose: a deployment that forgot to set it should
        show no URL rather than hand a caller a localhost one that silently fails.
        """
        if not self.api_external_url and self.environment == "local":
            self.api_external_url = f"http://localhost:{self.api_port}"
        return self

    @model_validator(mode="after")
    def agent_default_within_organization_default(self) -> Self:
        """An Agent's limit may never exceed its Organization's, so a default that did
        would put every new Agent in breach from its first call."""
        if self.agent_default_llm_budget_usd > self.organization_default_llm_budget_usd:
            raise ValueError("AGENT_DEFAULT_LLM_BUDGET_USD must not exceed ORGANIZATION_DEFAULT_LLM_BUDGET_USD")
        return self

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
    def memory_cost_key_hashes(self) -> frozenset[str]:
        return frozenset(part.strip() for part in self.memory_litellm_key_hashes.split(",") if part.strip())

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
