"""Sparkline widget using textual-plotext for real plots."""

from datetime import datetime

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Static
from textual_plotext import PlotextPlot


class SparklineWidget(Container):
    """
    Sparkline widget displaying a single metric over time.

    Uses textual-plotext for real plotting with braille/block characters.
    """

    DEFAULT_CSS = """
    SparklineWidget {
        height: 7;
        border: solid $primary-lighten-2;
        padding: 0 1;
        margin: 0 0 1 0;
    }

    SparklineWidget > .sparkline-title {
        height: 1;
        text-style: bold;
        color: $accent;
    }

    SparklineWidget > PlotextPlot {
        height: 5;
    }
    """

    def __init__(
        self,
        metric_name: str,
        label: str,
        unit: str = "",
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ):
        """
        Initialize sparkline widget.

        Args:
            metric_name: Metric identifier (cpu_pct, mem_pct, etc)
            label: Display label
            unit: Unit suffix (%, ms, etc)
            name: Widget name
            id: Widget ID
            classes: CSS classes
        """
        super().__init__(name=name, id=id, classes=classes)
        self.metric_name = metric_name
        self.label = label
        self.unit = unit
        self._current_value: float | None = None

    def compose(self) -> ComposeResult:
        """Compose child widgets."""
        yield Static("", classes="sparkline-title", id=f"{self.metric_name}-title")
        yield PlotextPlot(id=f"{self.metric_name}-plot")

    def on_mount(self) -> None:
        """Initialize plot on mount."""
        self._update_title()

    def _update_title(self) -> None:
        """Update title with current value."""
        title_widget = self.query_one(f"#{self.metric_name}-title", Static)
        if self._current_value is not None:
            title = f"{self.label}: {self._current_value:.1f}{self.unit}"
        else:
            title = f"{self.label}: --"
        title_widget.update(title)

    def update_data(self, points: list[tuple[datetime, float]]) -> None:
        """
        Update sparkline with new data points.

        Args:
            points: List of (timestamp, value) tuples, sorted ascending
        """
        if not points:
            return

        # Update current value (last point)
        self._current_value = points[-1][1]
        self._update_title()

        # Get plot widget
        plot = self.query_one(f"#{self.metric_name}-plot", PlotextPlot)

        # Extract x (timestamps) and y (values)
        # Convert timestamps to seconds since first point for plotting
        if len(points) > 1:
            base_ts = points[0][0].timestamp()
            x_values = [(p[0].timestamp() - base_ts) / 60 for p in points]  # minutes
        else:
            x_values = [0]

        y_values = [p[1] for p in points]

        # Clear and configure plot
        plt = plot.plt
        plt.clear_figure()

        # Clean look: no axes labels, just the plot
        plt.theme("clear")
        plt.plot_size(width=None, height=5)

        # Plot as line
        plt.plot(x_values, y_values, marker="braille")

        # Set y-axis limits based on metric type
        if self.metric_name in ["cpu_pct", "mem_pct"]:
            plt.ylim(0, 100)
        elif "load" in self.metric_name:
            max_load = max(y_values) if y_values else 1.0
            plt.ylim(0, max(max_load * 1.2, 1.0))
        else:
            # Auto-range for other metrics
            if y_values:
                min_val = min(y_values)
                max_val = max(y_values)
                padding = (max_val - min_val) * 0.1 or 1.0
                plt.ylim(min_val - padding, max_val + padding)

        # Refresh plot
        plot.refresh()

    def clear(self) -> None:
        """Clear sparkline data."""
        self._current_value = None
        self._update_title()

        plot = self.query_one(f"#{self.metric_name}-plot", PlotextPlot)
        plt = plot.plt
        plt.clear_figure()
        plot.refresh()
