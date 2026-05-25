"""Application configuration using Pydantic Settings."""
from typing import Annotated

from pydantic import Field, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    postgres_url: Annotated[
        PostgresDsn,
        Field(
            description="PostgreSQL connection URL with asyncpg driver",
            examples=["postgresql+asyncpg://user:pass@localhost:5432/rp"],
        ),
    ]

    jwt_secret: Annotated[
        str,
        Field(
            min_length=32,
            description="Secret key for JWT enrollment token signing (HS512)",
        ),
    ]

    jwt_algorithm: str = "HS512"

    server_url: Annotated[
        str,
        Field(
            default="http://localhost:8080",
            description="Public server URL returned to agents in enrollment response",
        ),
    ]

    heartbeat_interval_s: Annotated[
        int,
        Field(
            default=30,
            ge=10,
            le=300,
            description="Default heartbeat interval for agents (seconds)",
        ),
    ]

    log_level: str = "INFO"


settings = Settings()
