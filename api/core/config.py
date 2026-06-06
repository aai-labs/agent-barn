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

    environment: str = "local"
    web_app_url: str = "http://localhost:3000"
    access_token_expire_minutes: int | None = None
    refresh_token_expire_days: int | None = None

    k8s_kubeconfig_path: str | None = None
    k8s_namespace: str = "agent-farm"

    openclaw_image: str = ""
    hermes_image: str = ""
    agent_token_encryption_key: str = ""
    litellm_api_key: str = ""
    litellm_base_url: str = ""
    litellm_secret_name: str = "litellm"
    agent_litellm_base_url: str = ""
    agent_image_pull_secret: str = ""
    agent_default_model: str = "litellm/qwen3.6-plus"
    api_external_url: str = ""
    skip_slack_token_validation: bool = False

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
