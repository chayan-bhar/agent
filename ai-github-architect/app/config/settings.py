"""
Application configuration via Pydantic Settings.

All settings are loaded from environment variables (or .env file).
Never hard-code values here — use defaults only for safe, non-secret settings.
"""
from __future__ import annotations

from enum import Enum
from functools import lru_cache
from typing import Optional

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnv(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LLMProvider(str, Enum):
    GEMINI = "gemini"
    OPENAI = "openai"  # future


class Settings(BaseSettings):
    """Central configuration for the AI GitHub Repository Architect."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ───────────────────────────────────────────────────────────
    app_env: AppEnv = AppEnv.DEVELOPMENT
    app_host: str = "0.0.0.0"
    app_port: int = Field(default=8000, ge=1, le=65535)
    app_debug: bool = False
    app_log_level: LogLevel = LogLevel.INFO
    app_secret_key: str = Field(
        default="CHANGE-ME",
        description="Secret key for signing tokens. Must be changed in production.",
    )

    @property
    def is_development(self) -> bool:
        return self.app_env == AppEnv.DEVELOPMENT

    @property
    def is_production(self) -> bool:
        return self.app_env == AppEnv.PRODUCTION

    # ── LLM Provider ─────────────────────────────────────────────────────────
    llm_provider: LLMProvider = LLMProvider.GEMINI
    gemini_api_key: str = Field(default="", description="Google Gemini API key")
    gemini_model: str = "gemini-2.0-flash"
    gemini_temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    gemini_max_output_tokens: int = Field(default=8192, ge=256)

    # ── GitHub ────────────────────────────────────────────────────────────────
    github_token: str = Field(default="", description="GitHub Personal Access Token")
    github_api_base_url: str = "https://api.github.com"
    github_max_file_size_kb: int = Field(default=500, ge=1)
    github_max_repo_size_mb: int = Field(default=100, ge=1)
    github_max_files_per_analysis: int = Field(default=150, ge=10)

    # ── PostgreSQL ────────────────────────────────────────────────────────────
    postgres_host: str = "localhost"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_db: str = "ai_github_architect"
    postgres_user: str = "architect"
    postgres_password: str = "architect_password_change_me"
    database_url: str = (
        "postgresql+asyncpg://architect:architect_password_change_me@localhost:5432/ai_github_architect"
    )

    @property
    def sync_database_url(self) -> str:
        """Sync URL for Alembic migrations."""
        return self.database_url.replace("+asyncpg", "+psycopg")

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_host: str = "localhost"
    redis_port: int = Field(default=6379, ge=1, le=65535)
    redis_db: int = Field(default=0, ge=0, le=15)
    redis_password: Optional[str] = None
    redis_url: str = "redis://localhost:6379/0"
    redis_github_cache_ttl: int = Field(default=3600, ge=60)   # seconds
    redis_llm_cache_ttl: int = Field(default=86400, ge=300)    # seconds

    # ── MCP ───────────────────────────────────────────────────────────────────
    github_mcp_server_module: str = "app.mcp.github_server.server"

    # ── LangSmith Tracing ─────────────────────────────────────────────────────
    langchain_tracing_v2: bool = False
    langchain_endpoint: str = "https://api.smith.langchain.com"
    langchain_api_key: str = ""
    langchain_project: str = "ai-github-architect"

    # ── Analysis Limits ───────────────────────────────────────────────────────
    analysis_timeout_seconds: int = Field(default=300, ge=30)
    max_concurrent_analyses: int = Field(default=5, ge=1)
    file_chunk_size_tokens: int = Field(default=3000, ge=500)
    max_tokens_per_agent: int = Field(default=30000, ge=1000)

    # ── Validators ────────────────────────────────────────────────────────────
    @field_validator("app_secret_key")
    @classmethod
    def secret_key_must_not_be_default_in_production(cls, v: str) -> str:
        # Production enforcement happens at runtime via model_validator
        return v

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        if self.is_production:
            if self.app_secret_key == "CHANGE-ME":
                raise ValueError("APP_SECRET_KEY must be changed in production")
            if not self.gemini_api_key:
                raise ValueError("GEMINI_API_KEY is required in production")
            if not self.github_token:
                raise ValueError("GITHUB_TOKEN is required in production")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached application settings singleton."""
    return Settings()
