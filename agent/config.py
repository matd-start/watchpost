"""Configuración del agente: se lee del entorno y de `.env`."""

import socket

from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentConfig(BaseSettings):
    """Cada campo se puede sobreescribir con una variable `VIGIA_*`."""

    model_config = SettingsConfigDict(env_prefix="VIGIA_", env_file=".env", extra="ignore")

    server_url: str = "http://127.0.0.1:8000"
    api_key: str = "cambia-esta-clave"
    host: str = socket.gethostname()
    interval_seconds: int = 10
    disk_path: str = ""
