"""Typed application settings, loaded from environment variables."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "coderag-mcp"
    public_host: str = "127.0.0.1"
    voyage_api_key: str = ""
    sqlite_db_path: str = "coderag.db"
    allowed_hosts: list[str] = ["github.com", "gitlab.com"]
    max_repo_size_mb: int = 200
    clone_timeout_s: int = 60
    max_file_count: int = 500
    pipeline_timeout_s: int = 120


def get_settings() -> Settings:
    return Settings()
