"""Host detail widget with multiple sparklines."""

from datetime import datetime

from textual.app import ComposeResult
from textual.containers import Container, Vertical, VerticalScroll
from textual.widgets import Static

from rp.dash.widgets.sparkline import SparklineWidget


class HostDetail(Container):
    """
    Host detail widget displaying selected host info and sparklines.

    Shows 6 sparklines vertically:
    - cpu_pct
    - mem_pct
    - load_1m
    - disk_io (placeholder)
    - net_rx (placeholder)
    - net_tx (placeholder)
    """

    DEFAULT_CSS = """
    HostDetail {
        border: solid $primary;
        padding: 1;
    }

    HostDetail > .host-header {
        height: 4;
        border-bottom: solid $primary-lighten-2;
        margin-bottom: 1;
        padding: 0 1;
    }

    HostDetail > .host-header .host-name {
        text-style: bold;
        color: $accent;
    }

    HostDetail > .host-header .host-info {
        color: $text-muted;
    }

    HostDetail > VerticalScroll {
        height: 1fr;
    }
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._current_host_id: str | None = None
        self._current_hostname: str | None = None

    def compose(self) -> ComposeResult:
        """Compose child widgets."""
        with Vertical(classes="host-header"):
            yield Static("No host selected", classes="host-name", id="host-name")
            yield Static("", classes="host-info", id="host-group")
            yield Static("", classes="host-info", id="host-last-seen")

        with VerticalScroll(id="sparklines-container"):
            yield SparklineWidget("cpu_pct", "CPU", "%", id="spark-cpu")
            yield SparklineWidget("mem_pct", "Memory", "%", id="spark-mem")
            yield SparklineWidget("load_1m", "Load 1m", "", id="spark-load")
            yield SparklineWidget("disk_io", "Disk I/O", "MB/s", id="spark-disk")
            yield SparklineWidget("net_rx", "Net RX", "MB/s", id="spark-net-rx")
            yield SparklineWidget("net_tx", "Net TX", "MB/s", id="spark-net-tx")

    def update_host_info(self, host_id: str, detail: dict) -> None:
        """
        Update host header information.

        Args:
            host_id: Host UUID
            detail: Host detail dict from /v1/hosts/{id}
        """
        self._current_host_id = host_id
        self._current_hostname = detail.get("hostname", "unknown")

        # Update header
        name_widget = self.query_one("#host-name", Static)
        name_widget.update(f"Host: {self._current_hostname}")

        group_widget = self.query_one("#host-group", Static)
        group = detail.get("group_name") or "default"
        group_widget.update(f"Group: {group}")

        last_seen_widget = self.query_one("#host-last-seen", Static)
        last_seen_str = detail.get("last_seen_at")
        if last_seen_str:
            last_seen = datetime.fromisoformat(last_seen_str.replace("Z", "+00:00"))
            now = datetime.now(last_seen.tzinfo)
            seconds_ago = int((now - last_seen).total_seconds())

            if seconds_ago < 60:
                time_ago = f"{seconds_ago}s ago"
            elif seconds_ago < 3600:
                time_ago = f"{seconds_ago // 60}m ago"
            else:
                time_ago = f"{seconds_ago // 3600}h ago"

            last_seen_widget.update(f"Last seen: {time_ago}")
        else:
            last_seen_widget.update("Last seen: never")

    def update_sparklines(
        self, series: dict[str, list[tuple[datetime, float]]]
    ) -> None:
        """
        Update sparklines with new data.

        Args:
            series: Dict mapping metric_name -> list[(timestamp, value)]
        """
        metric_map = {
            "cpu_pct": "spark-cpu",
            "mem_pct": "spark-mem",
            "load_1m": "spark-load",
            "disk_io": "spark-disk",
            "net_rx": "spark-net-rx",
            "net_tx": "spark-net-tx",
        }

        for metric, widget_id in metric_map.items():
            widget = self.query_one(f"#{widget_id}", SparklineWidget)
            points = series.get(metric, [])
            if points:
                widget.update_data(points)
            else:
                # No data for this metric (e.g., disk_io not implemented yet)
                widget.clear()

    def clear(self) -> None:
        """Clear all sparklines and reset header."""
        self._current_host_id = None
        self._current_hostname = None

        name_widget = self.query_one("#host-name", Static)
        name_widget.update("No host selected")

        group_widget = self.query_one("#host-group", Static)
        group_widget.update("")

        last_seen_widget = self.query_one("#host-last-seen", Static)
        last_seen_widget.update("")

        # Clear all sparklines
        for widget in self.query(SparklineWidget):
            widget.clear()
