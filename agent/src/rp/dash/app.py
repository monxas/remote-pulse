"""Main TUI application for Remote-Pulse dashboard."""

import asyncio
from datetime import datetime, timezone

import httpx
import structlog
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.widgets import Footer, Static
from textual.worker import Worker, WorkerState

from rp.dash.api_client import AsyncAPIClient
from rp.dash.messages import (
    HostDetailRefreshed,
    HostSelected,
    HostsRefreshed,
    ServerError,
    SparklineDataReady,
)
from rp.dash.widgets import FooterStatus, HostDetail, HostList

logger = structlog.get_logger(__name__)


class RemotePulseApp(App):
    """
    Remote-Pulse TUI Dashboard.

    Three-pane layout:
    - Left: Host list with status indicators (30 cols)
    - Center: Host detail with sparklines (expandable)
    - Right: Logs/Exec placeholder (40 cols) - F4 TODO
    """

    CSS = """
    Screen {
        layout: grid;
        grid-size: 3;
        grid-columns: 32 1fr 42;
        grid-rows: 1fr auto;
    }

    #left-pane {
        row-span: 1;
    }

    #center-pane {
        row-span: 1;
    }

    #right-pane {
        row-span: 1;
        border: solid $primary;
        padding: 1;
    }

    #right-pane .placeholder {
        color: $text-muted;
        text-style: italic;
    }

    FooterStatus {
        column-span: 3;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", priority=True),
        Binding("r", "refresh", "Refresh", priority=True),
        Binding("question_mark", "help", "Help"),
        Binding("w", "change_window", "Window"),
        Binding("s", "change_series", "Series"),
        Binding("c", "connect_ssh", "SSH"),
        Binding("e", "exec_command", "Exec"),
    ]

    def __init__(self, server_url: str):
        """
        Initialize Remote-Pulse dashboard app.

        Args:
            server_url: Server base URL
        """
        super().__init__()
        self.server_url = server_url
        self.api_client = AsyncAPIClient(server_url)
        self._selected_host_id: str | None = None
        self._refresh_interval = 2.0  # seconds
        self._window = "5m"  # Default sparkline window
        self._metrics = ["cpu_pct", "mem_pct", "load_1m"]  # Active metrics
        self._refresh_worker: Worker | None = None

    def compose(self) -> ComposeResult:
        """Compose application layout."""
        with Container(id="left-pane"):
            yield HostList(id="host-list")

        with Container(id="center-pane"):
            yield HostDetail(id="host-detail")

        with VerticalScroll(id="right-pane"):
            yield Static("Logs (F4)", classes="placeholder")
            yield Static("", classes="placeholder")
            yield Static("Command execution coming in F4", classes="placeholder")
            yield Static("", classes="placeholder")
            yield Static("SSH console coming in F6", classes="placeholder")

        yield FooterStatus(server_url=self.server_url, id="footer-status")
        yield Footer()

    async def on_mount(self) -> None:
        """Initialize app on mount."""
        logger.info("dashboard starting", server_url=self.server_url)

        # Connect API client
        try:
            await self.api_client.connect()
        except Exception as e:
            logger.error("failed to connect to server", error=str(e))
            self.post_message(ServerError(f"Connection failed: {e}"))
            return

        # Initial refresh
        self._start_refresh_worker()

    async def on_unmount(self) -> None:
        """Cleanup on unmount."""
        logger.info("dashboard stopping")

        # Stop refresh worker
        if self._refresh_worker:
            self._refresh_worker.cancel()

        # Close API client
        await self.api_client.close()

    def _start_refresh_worker(self) -> None:
        """Start background worker for periodic refresh."""
        if self._refresh_worker and self._refresh_worker.state == WorkerState.RUNNING:
            return

        self._refresh_worker = self.run_worker(
            self._refresh_loop(),
            name="refresh",
            group="refresh",
            exclusive=True,
        )

    async def _refresh_loop(self) -> None:
        """
        Background worker that refreshes data every N seconds.

        F3 MVP: Uses polling. F4 TODO: Replace with WebSocket subscribe.
        """
        while True:
            try:
                await self._fetch_hosts()

                if self._selected_host_id:
                    await self._fetch_host_detail(self._selected_host_id)
                    await self._fetch_sparklines(self._selected_host_id)

                # Wait before next refresh
                await asyncio.sleep(self._refresh_interval)

            except httpx.HTTPError as e:
                logger.error("refresh failed", error=str(e))
                self.post_message(ServerError(f"Server unreachable: {e}"))
                await asyncio.sleep(5.0)  # Retry after 5s on error

            except Exception as e:
                logger.error("unexpected error in refresh loop", error=str(e))
                await self.sleep(5.0)

    async def _fetch_hosts(self) -> None:
        """Fetch host list from server."""
        hosts = await self.api_client.list_hosts()
        timestamp = datetime.now(timezone.utc)
        self.post_message(HostsRefreshed(hosts=hosts, timestamp=timestamp))

    async def _fetch_host_detail(self, host_id: str) -> None:
        """Fetch host detail from server."""
        detail = await self.api_client.get_host_detail(host_id)
        self.post_message(HostDetailRefreshed(host_id=host_id, detail=detail))

    async def _fetch_sparklines(self, host_id: str) -> None:
        """Fetch sparkline data from server."""
        series = await self.api_client.get_sparkline(
            host_id=host_id,
            metrics=self._metrics,
            window=self._window,
        )
        self.post_message(SparklineDataReady(host_id=host_id, series=series))

    def on_hosts_refreshed(self, message: HostsRefreshed) -> None:
        """Handle hosts data refresh."""
        host_list = self.query_one("#host-list", HostList)
        host_list.update_hosts(message.hosts)

        footer = self.query_one("#footer-status", FooterStatus)
        footer.update_refresh(message.timestamp)

    def on_host_selected(self, message: HostSelected) -> None:
        """Handle host selection."""
        logger.info("host selected", host_id=message.host_id, hostname=message.hostname)
        self._selected_host_id = message.host_id

        # Trigger immediate fetch for selected host
        self.run_worker(self._fetch_host_detail(message.host_id), exclusive=False)
        self.run_worker(self._fetch_sparklines(message.host_id), exclusive=False)

    def on_host_detail_refreshed(self, message: HostDetailRefreshed) -> None:
        """Handle host detail refresh."""
        if message.host_id == self._selected_host_id:
            host_detail = self.query_one("#host-detail", HostDetail)
            host_detail.update_host_info(message.host_id, message.detail)

    def on_sparkline_data_ready(self, message: SparklineDataReady) -> None:
        """Handle sparkline data ready."""
        if message.host_id == self._selected_host_id:
            host_detail = self.query_one("#host-detail", HostDetail)
            host_detail.update_sparklines(message.series)

    def on_server_error(self, message: ServerError) -> None:
        """Handle server error."""
        footer = self.query_one("#footer-status", FooterStatus)
        footer.update_error(message.error)

    def action_refresh(self) -> None:
        """Force immediate refresh."""
        logger.info("manual refresh triggered")
        self.run_worker(self._fetch_hosts(), exclusive=False)

        if self._selected_host_id:
            self.run_worker(
                self._fetch_host_detail(self._selected_host_id), exclusive=False
            )
            self.run_worker(
                self._fetch_sparklines(self._selected_host_id), exclusive=False
            )

    def action_help(self) -> None:
        """Show help screen."""
        # TODO F3: Implement modal help screen
        self.notify(
            "Help: q=quit r=refresh w=window s=series c=ssh e=exec", title="Keybindings"
        )

    def action_change_window(self) -> None:
        """Change sparkline time window."""
        # TODO F3: Implement window selector modal
        windows = ["5m", "15m", "1h", "6h", "24h"]
        current_idx = windows.index(self._window) if self._window in windows else 0
        next_idx = (current_idx + 1) % len(windows)
        self._window = windows[next_idx]

        self.notify(f"Window changed to {self._window}", title="Sparkline Window")

        # Refresh sparklines with new window
        if self._selected_host_id:
            self.run_worker(
                self._fetch_sparklines(self._selected_host_id), exclusive=False
            )

    def action_change_series(self) -> None:
        """Change active sparkline series."""
        # TODO F3: Implement series selector modal
        self.notify(
            "Series filter not yet implemented", severity="warning", title="TODO"
        )

    def action_connect_ssh(self) -> None:
        """Connect SSH to selected host."""
        # TODO F6: Implement SSH console
        self.notify("SSH console coming in F6", severity="information", title="TODO")

    def action_exec_command(self) -> None:
        """Execute remote command on selected host."""
        # TODO F4: Implement remote exec
        self.notify("Remote exec coming in F4", severity="information", title="TODO")


async def run_dashboard(server_url: str) -> None:
    """
    Run the dashboard TUI app.

    Args:
        server_url: Server base URL
    """
    app = RemotePulseApp(server_url)
    await app.run_async()
