"""Application configuration using Pydantic Settings."""

from typing import Annotated

from pydantic import Field, PostgresDsn, SecretStr
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

    # Tailscale API integration (F2)
    tailscale_api_key: Annotated[
        SecretStr | None,
        Field(
            default=None,
            description="Tailscale API key for ephemeral auth-key generation",
        ),
    ] = None

    tailscale_tailnet: Annotated[
        str,
        Field(
            default="-",
            description='Tailnet identifier ("-" = default tailnet of API key owner)',
        ),
    ] = "-"

    tailscale_authkey_expiry_seconds: Annotated[
        int,
        Field(
            default=86400,
            ge=60,
            le=604800,
            description="Expiration time for ephemeral auth-keys (seconds, max 7d)",
        ),
    ] = 86400

    tailscale_tags_by_group: dict[str, str] = Field(
        default_factory=lambda: {
            "prod": "tag:rp-agent-prod",
            "family": "tag:rp-agent-family",
            "iarq": "tag:rp-agent-iarq",
            "default": "tag:rp-agent-default",
        },
        description="Mapping of group names to Tailscale ACL tags",
    )


settings = Settings()
