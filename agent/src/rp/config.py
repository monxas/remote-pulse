"""Configuration management for Remote-Pulse agent."""

import os
import sys
import tomllib
from pathlib import Path

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger()

# Config file location
if sys.platform == "win32":
    DEFAULT_CONFIG_PATH = Path("C:/ProgramData/rp/config.toml")
    DEFAULT_STATE_DIR = Path("C:/ProgramData/rp")
else:
    DEFAULT_CONFIG_PATH = Path("/etc/rp/config.toml")
    DEFAULT_STATE_DIR = Path("/var/lib/rp")


class AgentConfig(BaseModel):
    """Agent configuration model."""

    host_id: str
    server_url: str
    heartbeat_interval_s: int = Field(default=30, ge=5, le=3600)
    # Phase 2.5: how often the agent pulls pending commands from the server.
    # Kept tight (5s default) so dashboard → execution latency feels live;
    # cheap to do because the server response is small and only returns rows
    # in a narrow approved-but-not-completed window.
    command_poll_interval_s: int = Field(default=5, ge=1, le=300)
    group: str | None = None


def load_config(config_path: Path | None = None) -> AgentConfig:
    """
    Load configuration from TOML file.

    Args:
        config_path: Optional path to config file, defaults to /etc/rp/config.toml

    Returns:
        AgentConfig instance

    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If config is invalid
    """
    if config_path is None:
        config_path = DEFAULT_CONFIG_PATH

    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}. Run 'rp install' first.")

    logger.debug("loading config", path=str(config_path))

    # stdlib tomllib: the project is `requires-python = ">=3.12"`, so the old
    # `if sys.version_info >= (3, 11)` guard could never take its else branch.
    with open(config_path, "rb") as f:
        data = tomllib.load(f)

    # Allow env var overrides for testing
    if "RP_SERVER_URL" in os.environ:
        data["server_url"] = os.environ["RP_SERVER_URL"]

    try:
        return AgentConfig(**data)
    except Exception as e:
        raise ValueError(f"Invalid config: {e}")


def save_config(config: AgentConfig, config_path: Path | None = None) -> None:
    """
    Save configuration to TOML file.

    Args:
        config: Configuration to save
        config_path: Optional path, defaults to /etc/rp/config.toml
    """
    if config_path is None:
        config_path = DEFAULT_CONFIG_PATH

    # Ensure directory exists
    config_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info("saving config", path=str(config_path))

    # Write TOML manually (no stdlib writer until 3.13)
    lines = [
        f'host_id = "{config.host_id}"',
        f'server_url = "{config.server_url}"',
        f"heartbeat_interval_s = {config.heartbeat_interval_s}",
    ]

    if config.group:
        lines.append(f'group = "{config.group}"')

    config_path.write_text("\n".join(lines) + "\n")

    # Secure permissions (Unix only)
    if sys.platform != "win32":
        os.chmod(config_path, 0o600)


def get_state_dir() -> Path:
    """Get agent state directory."""
    state_dir = DEFAULT_STATE_DIR
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir


def config_exists() -> bool:
    """Check if config file exists."""
    return DEFAULT_CONFIG_PATH.exists()
