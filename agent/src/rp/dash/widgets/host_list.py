"""Host list widget with status indicators."""

from datetime import datetime, timezone

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import DataTable

from rp.dash.messages import HostSelected


class HostList(Container):
    """
    Host list widget displaying all registered hosts with status.

    Color status:
    - Green: last_seen < 60s ago
    - Yellow: 60-180s ago
    - Red: > 180s ago
    """

    DEFAULT_CSS = """
    HostList {
        width: 32;
        border: solid $primary;
        padding: 0;
    }

    HostList > DataTable {
        height: 100%;
    }
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._hosts: list[dict] = []

    def compose(self) -> ComposeResult:
        """Compose child widgets."""
        table = DataTable(id="host-table", cursor_type="row", zebra_stripes=True)
        table.focus()
        yield table

    def on_mount(self) -> None:
        """Initialize table on mount."""
        table = self.query_one(DataTable)
        table.add_columns("Host", "Status")
        table.cursor_type = "row"

    def update_hosts(self, hosts: list[dict]) -> None:
        """
        Update host list with new data.

        Args:
            hosts: List of host summary objects from /v1/hosts
        """
        self._hosts = sorted(hosts, key=lambda h: h.get("hostname", ""))

        table = self.query_one(DataTable)
        table.clear()

        now = datetime.now(timezone.utc)

        for host in self._hosts:
            hostname = host.get("hostname", "unknown")
            last_seen_str = host.get("last_seen_at")

            if last_seen_str:
                last_seen = datetime.fromisoformat(last_seen_str.replace("Z", "+00:00"))
                seconds_ago = (now - last_seen).total_seconds()

                # Status indicator
                if seconds_ago < 60:
                    status = Text("▲", style="bold green")
                    status_text = f"{int(seconds_ago)}s"
                elif seconds_ago < 180:
                    status = Text("▲", style="bold yellow")
                    status_text = f"{int(seconds_ago)}s"
                elif seconds_ago < 3600:
                    status = Text("⏸", style="bold orange1")
                    status_text = f"{int(seconds_ago / 60)}m"
                else:
                    status = Text("▼", style="bold red")
                    hours = int(seconds_ago / 3600)
                    status_text = f"{hours}h"

                status.append(f" {status_text}")
            else:
                status = Text("?", style="bold dim")

            # Add row with host_id as key
            host_id = host.get("id", "")
            table.add_row(hostname, status, key=host_id)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection."""
        if event.row_key is None:
            return

        host_id = str(event.row_key.value)

        # Find hostname for this host_id
        hostname = "unknown"
        for host in self._hosts:
            if host.get("id") == host_id:
                hostname = host.get("hostname", "unknown")
                break

        # Post message to app
        self.post_message(HostSelected(host_id=host_id, hostname=hostname))
