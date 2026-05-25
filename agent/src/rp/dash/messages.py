"""Custom Textual messages for Remote-Pulse dashboard."""

from datetime import datetime
from typing import Any

from textual.message import Message


class HostsRefreshed(Message):
    """Emitted when host list data is refreshed from server."""

    def __init__(self, hosts: list[dict[str, Any]], timestamp: datetime) -> None:
        self.hosts = hosts
        self.timestamp = timestamp
        super().__init__()


class HostSelected(Message):
    """Emitted when a host is selected in the list."""

    def __init__(self, host_id: str, hostname: str) -> None:
        self.host_id = host_id
        self.hostname = hostname
        super().__init__()


class HostDetailRefreshed(Message):
    """Emitted when host detail data is refreshed."""

    def __init__(self, host_id: str, detail: dict[str, Any]) -> None:
        self.host_id = host_id
        self.detail = detail
        super().__init__()


class SparklineDataReady(Message):
    """Emitted when sparkline data is fetched."""

    def __init__(
        self, host_id: str, series: dict[str, list[tuple[datetime, float]]]
    ) -> None:
        self.host_id = host_id
        self.series = series
        super().__init__()


class ServerError(Message):
    """Emitted when server communication fails."""

    def __init__(self, error: str) -> None:
        self.error = error
        super().__init__()
