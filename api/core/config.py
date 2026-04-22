from functools import lru_cache

from dotenv import load_dotenv
from pydantic import PostgresDsn
from pydantic_settings import BaseSettings

load_dotenv()


class Config(BaseSettings):
    db_connection_url: PostgresDsn
    secret_signing_key: str
    super_user_credentials: str
    email_server_credential: str
    email_smtp_server: str

    environment: str = "local"
    web_app_url: str = "http://localhost:3000"
    access_token_expire_minutes: int | None = None
    refresh_token_expire_days: int | None = None


@lru_cache
def get_config() -> Config:
    config = Config()  # ty: ignore[missing-argument]
    return config
