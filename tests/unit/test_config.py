"""Unit tests for configuration module."""
import os
import tempfile
from pathlib import Path
import pytest
from unittest.mock import patch
from app.config import Settings, get_settings, ensure_dirs


class TestSettings:
    def test_default_settings(self, monkeypatch):
        for key in ["SOCKS5_PROXY", "LLM_API_BASE", "LLM_API_KEY", "LLM_MODEL",
                    "DATABASE_PATH", "ARTICLES_DIR", "TRANSCRIPTS_DIR",
                    "ADMIN_PASSWORD", "SECRET_KEY", "WORKER_TOKEN",
                    "HOST", "PORT", "RATE_LIMIT_SECONDS", "MAX_RETRIES"]:
            monkeypatch.delenv(key, raising=False)
        settings = Settings()
        assert settings.socks5_proxy == ""
        assert settings.llm_api_base == "https://api.openai.com/v1"
        assert settings.llm_api_key == ""
        assert settings.llm_model == "gpt-4o-mini"
        assert settings.admin_password == "changeme"
        assert settings.secret_key == "changeme"
        assert settings.worker_token == "changeme"
        assert settings.host == "0.0.0.0"
        assert settings.port == 8000
        assert settings.rate_limit_seconds == 3.0
        assert settings.max_retries == 3

    def test_env_var_override(self, monkeypatch):
        env = {
            "SOCKS5_PROXY": "socks5h://proxy:1080",
            "LLM_API_KEY": "test_api_key",
            "LLM_MODEL": "gpt-4",
            "ADMIN_PASSWORD": "secure_password",
            "SECRET_KEY": "secure_secret_key",
            "WORKER_TOKEN": "secure_worker_token",
            "HOST": "127.0.0.1",
            "PORT": "9000",
            "RATE_LIMIT_SECONDS": "1.5",
            "MAX_RETRIES": "5"
        }
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        settings = Settings()
        assert settings.socks5_proxy == "socks5h://proxy:1080"
        assert settings.llm_api_key == "test_api_key"
        assert settings.llm_model == "gpt-4"
        assert settings.admin_password == "secure_password"
        assert settings.host == "127.0.0.1"
        assert settings.port == 9000
        assert settings.rate_limit_seconds == 1.5
        assert settings.max_retries == 5

    def test_database_path_property(self):
        assert isinstance(Settings().database_file, Path)

    def test_articles_dir_property(self):
        assert isinstance(Settings().articles_dir_path, Path)

    def test_transcripts_dir_property(self):
        assert isinstance(Settings().transcripts_dir_path, Path)

    def test_custom_paths(self, monkeypatch, tmp_path):
        db = str(tmp_path / "custom.db")
        art = str(tmp_path / "articles")
        trn = str(tmp_path / "transcripts")
        monkeypatch.setenv("DATABASE_PATH", db)
        monkeypatch.setenv("ARTICLES_DIR", art)
        monkeypatch.setenv("TRANSCRIPTS_DIR", trn)
        s = Settings()
        assert str(s.database_file) == db
        assert str(s.articles_dir_path) == art
        assert str(s.transcripts_dir_path) == trn


class TestConfigurationCaching:
    def test_get_settings_caching(self):
        assert get_settings() is get_settings()


class TestEnsureDirs:
    def test_ensure_dirs_creates(self, monkeypatch, tmp_path):
        """Test ensure_dirs creates directories."""
        data_dir = tmp_path / "data"
        articles = tmp_path / "articles"
        transcripts = tmp_path / "transcripts"
        db_path = str(data_dir / "test.db")

        # Create a mock settings object
        mock_settings = Settings(
            database_path=db_path,
            articles_dir=str(articles),
            transcripts_dir=str(transcripts)
        )

        assert not data_dir.exists()
        assert not articles.exists()
        assert not transcripts.exists()

        # Patch the settings used by ensure_dirs
        with patch('app.config.settings', mock_settings):
            ensure_dirs()

        assert data_dir.exists()
        assert articles.exists()
        assert transcripts.exists()
        # Idempotent
        with patch('app.config.settings', mock_settings):
            ensure_dirs()

    def test_ensure_dirs_with_existing(self, monkeypatch, tmp_path):
        """Test ensure_dirs when dirs already exist."""
        articles = tmp_path / "articles"
        articles.mkdir()

        mock_settings = Settings(
            database_path=str(tmp_path / "test.db"),
            articles_dir=str(articles),
            transcripts_dir=str(tmp_path / "transcripts")
        )

        with patch('app.config.settings', mock_settings):
            ensure_dirs()
        assert articles.exists()
        assert (tmp_path / "transcripts").exists()


class TestConfigValidation:
    def test_insecure_defaults(self, monkeypatch):
        for key in ["ADMIN_PASSWORD", "SECRET_KEY", "WORKER_TOKEN"]:
            monkeypatch.delenv(key, raising=False)
        s = Settings()
        assert s.admin_password == "changeme"
        assert s.secret_key == "changeme"
        assert s.worker_token == "changeme"

    def test_proxy_config(self, monkeypatch):
        monkeypatch.setenv("SOCKS5_PROXY", "socks5h://p:1080")
        assert Settings().socks5_proxy == "socks5h://p:1080"

    def test_llm_config(self, monkeypatch):
        monkeypatch.setenv("LLM_API_BASE", "https://custom.example.com/v1")
        monkeypatch.setenv("LLM_API_KEY", "custom-key")
        monkeypatch.setenv("LLM_MODEL", "custom-model")
        s = Settings()
        assert s.llm_api_base == "https://custom.example.com/v1"
        assert s.llm_api_key == "custom-key"
        assert s.llm_model == "custom-model"

    def test_rate_limiting(self, monkeypatch):
        monkeypatch.setenv("RATE_LIMIT_SECONDS", "0.5")
        monkeypatch.setenv("MAX_RETRIES", "10")
        s = Settings()
        assert s.rate_limit_seconds == 0.5
        assert s.max_retries == 10

    def test_server_config(self, monkeypatch):
        monkeypatch.setenv("HOST", "localhost")
        monkeypatch.setenv("PORT", "3000")
        s = Settings()
        assert s.host == "localhost"
        assert s.port == 3000
