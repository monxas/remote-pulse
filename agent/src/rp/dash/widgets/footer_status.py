"""Footer status bar widget."""

from datetime import datetime

from textual.widgets import Static


class FooterStatus(Static):
    """
    Custom footer status bar showing refresh time and server URL.

    Complements Textual's built-in Footer for key bindings.
    """

    DEFAULT_CSS = """
    FooterStatus {
        dock: bottom;
        height: 1;
        background: $panel;
        color: $text;
        padding: 0 1;
        text-style: dim;
    }
    """

    def __init__(self, server_url: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.server_url = server_url
        self._last_refresh: datetime | None = None
        self._error: str | None = None

    def on_mount(self) -> None:
        """Initialize status bar on mount."""
        self._update_status()

    def update_refresh(self, timestamp: datetime) -> None:
        """
        Update last refresh timestamp.

        Args:
            timestamp: Refresh time
        """
        self._last_refresh = timestamp
        self._error = None
        self._update_status()

    def update_error(self, error: str) -> None:
        """
        Display error message.

        Args:
            error: Error message
        """
        self._error = error
        self._update_status()

    def _update_status(self) -> None:
        """Render status bar text."""
        parts = []

        if self._error:
            parts.append(f"✗ Error: {self._error}")
        elif self._last_refresh:
            now = datetime.now(self._last_refresh.tzinfo or None)
            seconds_ago = int((now - self._last_refresh).total_seconds())
            parts.append(f"Last refresh: {seconds_ago}s ago")
        else:
            parts.append("Connecting...")

        parts.append(f"Server: {self.server_url}")
        parts.append("q: quit | r: refresh | ?: help")

        self.update(" | ".join(parts))
