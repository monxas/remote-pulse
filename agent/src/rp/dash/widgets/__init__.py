"""TUI widgets for Remote-Pulse dashboard."""

from rp.dash.widgets.footer_status import FooterStatus
from rp.dash.widgets.host_detail import HostDetail
from rp.dash.widgets.host_list import HostList
from rp.dash.widgets.sparkline import SparklineWidget

__all__ = ["FooterStatus", "HostDetail", "HostList", "SparklineWidget"]
