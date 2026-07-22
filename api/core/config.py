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
    super_user_credentials: str
    super_user_full_name: str = "Super User"
    email_server_credential: str | None = None
    email_smtp_server: str | None = None
    # Optional visible "From" for outgoing mail. The SMTP login always uses the email
    # in EMAIL_SERVER_CREDENTIAL; set EMAIL_FROM_ADDRESS to send *as* another address
    # (e.g. no-reply@agentbarn.dev) while still authenticating with that credential.
    # For good deliverability the sending domain should be authorized by the SMTP
    # provider and DKIM/SPF/DMARC-configured. Defaults to the credential email.
    email_from_address: str | None = None
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
    api_external_url: str = ""
    ingest_base_url: str = (
        "http://agentfarm-api.agent-farm.svc.cluster.local:8001/ingest/v1"
    )
    skip_slack_token_validation: bool = False
    skip_telegram_token_validation: bool = False
    slack_directory_cache_ttl_seconds: int = 600
    # Socket timeout for Slack Web API calls. Large sweeps (e.g. users.list can be
    # ~320KB) are slow over a poor link; too tight a timeout cuts the body off
    # mid-stream (IncompleteRead). Generous default; in-cluster latency is low.
    slack_request_timeout_seconds: int = 30

    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_models_cache_ttl_seconds: int = 3600
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

    @property
    def is_email_delivery_enabled(self) -> bool:
        return bool(
            (self.email_server_credential or "").strip()
            and (self.email_smtp_server or "").strip()
        )


@lru_cache
def get_config() -> Config:
    config = Config()  # ty: ignore[missing-argument]
    return config
