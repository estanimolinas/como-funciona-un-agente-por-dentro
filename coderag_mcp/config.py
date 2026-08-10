"""Typed application settings, loaded from environment variables."""
from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    # env_prefix="CODERAG_" means every field below (except voyage_api_key, which
    # opts out via its own validation_alias) is only read from CODERAG_<FIELD>,
    # never from a bare/unprefixed env var of the same name - important on PaaS
    # platforms where generic names like ALLOWED_HOSTS are common and could
    # otherwise silently override this app's settings.
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", env_prefix="CODERAG_", populate_by_name=True
    )

    app_name: str = "coderag-mcp"
    public_host: str = "127.0.0.1"
    # Deliberately opts out of the CODERAG_ prefix (via validation_alias) so its
    # env var stays VOYAGE_API_KEY, matching Voyage's own SDK/docs convention.
    voyage_api_key: str = Field(default="", validation_alias="VOYAGE_API_KEY")
    sqlite_db_path: str = "coderag.db"
    api_key: str = ""
    # NoDecode: opt this list field out of pydantic-settings' default
    # JSON-array-only env parsing, so the validator below can also accept a
    # plain comma-separated string (the natural thing to type for an env var).
    allowed_hosts: Annotated[list[str], NoDecode] = ["github.com", "gitlab.com"]
    max_repo_size_mb: int = 200
    clone_timeout_s: int = 60
    max_file_count: int = 500
    pipeline_timeout_s: int = 120

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def _parse_allowed_hosts(cls, v: object) -> object:
        """Accept a plain comma-separated string (e.g.
        ``CODERAG_ALLOWED_HOSTS=github.com,gitlab.com``) in addition to
        JSON-array syntax (``CODERAG_ALLOWED_HOSTS=["github.com"]``)."""
        if isinstance(v, str):
            stripped = v.strip()
            if stripped.startswith("["):
                import json

                return json.loads(stripped)
            return [host.strip() for host in stripped.split(",") if host.strip()]
        return v


def validate_settings(settings: Settings) -> None:
    """Raise RuntimeError with an actionable message if a required setting is
    missing. Called once at startup by both api/main.py's create_app() and
    mcp_server/server.py's _lifespan - fails fast rather than accepting requests
    and failing confusingly on the first real Voyage call.

    CODERAG_API_KEY is intentionally NOT validated here: empty/unset is a
    supported dev-mode value (see api/auth.py's validate_api_key), not a
    misconfiguration.
    """
    if not settings.voyage_api_key:
        raise RuntimeError(
            "VOYAGE_API_KEY is required - set it in .env or the environment. "
            "See README.md's Quickstart."
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
