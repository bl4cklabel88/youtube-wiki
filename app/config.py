"""Application configuration loaded from environment variables.

Uses pydantic-settings-style loading via python-dotenv + pydantic.
All settings can be overridden with environment variables or a `.env` file.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Load .env from the repository root (two levels up from app/config.py)
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Settings(BaseSettings):
    """Central settings object for the whole application."""

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Proxy -------------------------------------------------------------
    socks5_proxy: str = Field(default="", description="SOCKS5 proxy URL e.g. socks5h://user:pass@host:port")

    # --- LLM Processing (OpenAI-compatible) --------------------------------
    llm_api_base: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"

    # --- Database / Storage ------------------------------------------------
    database_path: str = str(BASE_DIR / "data" / "wiki.db")
    articles_dir: str = str(BASE_DIR / "data" / "articles")
    transcripts_dir: str = str(BASE_DIR / "data" / "transcripts")

    # --- Admin --------------------------------------------------------------
    admin_password: str = "changeme"
    secret_key: str = "changeme"
    worker_token: str = "changeme"

    # --- Server -------------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8000

    # --- Scraping -----------------------------------------------------------
    rate_limit_seconds: float = 3.0
    max_retries: int = 3

    # --- Derived helpers -----------------------------------------------------
    @property
    def database_file(self) -> Path:
        return Path(self.database_path)

    @property
    def articles_dir_path(self) -> Path:
        return Path(self.articles_dir)

    @property
    def transcripts_dir_path(self) -> Path:
        return Path(self.transcripts_dir)


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings."""
    return Settings()


settings = get_settings()


def ensure_dirs() -> None:
    """Make sure storage directories exist."""
    for d in (settings.database_file.parent, settings.articles_dir_path, settings.transcripts_dir_path):
        d.mkdir(parents=True, exist_ok=True)
