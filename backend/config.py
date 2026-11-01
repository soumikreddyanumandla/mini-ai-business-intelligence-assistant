"""
Application Configuration Module
--------------------------------
Provides strongly-typed settings using pydantic-settings, reading environment
variables from .env file or system environment with sensible defaults.
"""

from pathlib import Path
from typing import Literal, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # Application Info
    APP_NAME: str = "Mini AI Business Intelligence Assistant"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False

    # Server Configuration
    API_HOST: str = "127.0.0.1"
    API_PORT: int = 8000
    STREAMLIT_PORT: int = 8501
    LOG_LEVEL: str = "INFO"

    # Database Configuration
    DATABASE_URL: str = f"sqlite:///{BASE_DIR / 'data' / 'bi_assistant.db'}"
    CSV_DATA_PATH: str = str(BASE_DIR / "data" / "sales.csv")

    # Generative AI Configuration
    # Supported providers: "gemini", "openai", "fallback"
    LLM_PROVIDER: Literal["gemini", "openai", "fallback"] = "gemini"
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-1.5-flash"

    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4o-mini"

    # Intent Router & Safety Settings
    MAX_QUERY_LENGTH: int = 500
    ALLOW_FALLBACK_ON_ERROR: bool = True

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
