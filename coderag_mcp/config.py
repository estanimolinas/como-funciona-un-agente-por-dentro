"""Typed application settings, loaded from environment variables."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "coderag-mcp"
    public_host: str = "127.0.0.1"


def get_settings() -> Settings:
    return Settings()
