from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = "postgresql+psycopg2://postgres:postgres@postgres:5432/newsbot"

    # Redis / Celery
    redis_url: str = "redis://redis:6379/0"

    # Auth
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 12

    # Encrypts secret Settings rows (telegram_bot_token, ai_api_key) at rest.
    # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    settings_encryption_key: str = ""

    # Telegram / AI: these env vars are only the *initial seed* value, copied
    # into the encrypted `settings` table on first boot. After that, the web
    # panel (Settings page) is authoritative — edit them there, not here.
    telegram_bot_token: str = ""
    target_channel_id: str = ""

    ai_provider: str = "openai"  # openai | anthropic | custom_openai_compatible
    ai_api_key: str = ""
    ai_api_base: str = ""  # override for custom_openai_compatible
    ai_model: str = "gpt-4o-mini"
    ai_temperature: float = 0.9
    ai_max_tokens: int = 800

    # Media storage
    media_root: str = "/app/media"

    # Misc
    env: str = "production"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
