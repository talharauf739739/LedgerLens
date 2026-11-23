"""Typed settings loaded from the environment (and `.env` in development).

Secrets never have defaults here. Locally they come from `.env` / Floci Key Vault;
in the cloud from Azure Key Vault via managed identity.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(StrEnum):
    FOUNDRY_LOCAL = "foundry_local"
    OLLAMA = "ollama"
    AZURE_FOUNDRY = "azure_foundry"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", env_prefix=""
    )

    env: str = Field(default="local", description="local | vm | azure")

    # --- LLM -----------------------------------------------------------------
    llm_provider: LLMProvider = LLMProvider.FOUNDRY_LOCAL
    llm_model: str = Field(
        default="phi-4-mini",
        description="Model alias (Foundry Local / Ollama) or deployment name (Azure).",
    )
    # Foundry Local: leave empty to discover the runtime-assigned port via the SDK.
    # Set it when the caller can't host the runtime (e.g. a container talking to the host).
    foundry_local_base_url: str | None = None
    ollama_base_url: str = "http://localhost:11434/v1"
    azure_foundry_endpoint: str | None = None
    azure_foundry_api_version: str = "2024-10-21"

    # --- Azure-compatible services (Floci locally) ---------------------------
    azure_storage_connection_string: SecretStr | None = None
    azure_storage_account_url: str | None = None  # cloud: used with DefaultAzureCredential
    blob_container: str = "documents"
    jobs_queue: str = "extraction-jobs"
    key_vault_url: str | None = None

    # --- Open-source services ------------------------------------------------
    database_url: SecretStr = SecretStr(
        "postgresql+asyncpg://ledgerlens:ledgerlens@localhost:5432/ledgerlens"
    )
    cache_url: str = "redis://localhost:6379/0"

    # --- API -----------------------------------------------------------------
    max_upload_mb: int = 20
    max_pages: int = 50
    cors_origins: list[str] = ["http://localhost:8501"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
