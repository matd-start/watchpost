"""Configuración del servidor: se lee del entorno y de `.env`."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Cada campo se puede sobreescribir con una variable `WATCHPOST_*`."""

    model_config = SettingsConfigDict(env_prefix="WATCHPOST_", env_file=".env", extra="ignore")

    api_key: str = "cambia-esta-clave"
    database_url: str = "sqlite:///data/watchpost.db"
    online_threshold_seconds: int = 60
    discord_webhook_url: str = ""
    alert_interval_seconds: int = 30
    rules_path: str = "rules.toml"


@lru_cache
def get_settings() -> Settings:
    """Una sola instancia por proceso: leer `.env` en cada petición sería un desperdicio."""
    return Settings()
