"""Tests for agent version reporting.

Regression guard for the bug where production hosts reported
``agent_version="main"`` in ``/v1/dash/hosts`` — the install.sh shell
script was sending the git ref (branch name) as ``agent_version`` in the
enroll payload instead of the actual installed package semver.

These tests pin the contract that ``rp.__version__`` (which feeds both
``rp --version`` and the ``MetricsCollector.collect_heartbeat_metrics``
payload) is a real SemVer string, never a git ref.
"""

import re
import tomllib
from pathlib import Path

import pytest

from rp import __version__
from rp.metrics import MetricsCollector


# Matches X.Y.Z with optional pre-release/build (PEP 440 / SemVer flavoured).
SEMVER_PATTERN = re.compile(
    r"^\d+\.\d+\.\d+([-+][0-9A-Za-z.\-]+)?$"
)

# Tokens that historically leaked into agent_version because they were
# the git ref/branch passed to install.sh, not the package version.
GIT_REF_BLOCKLIST = frozenset(
    {"main", "master", "head", "latest", "develop", "dev", "trunk", ""}
)


def test_version_is_semver():
    """__version__ must be a real semver, not a git ref like 'main'."""
    assert SEMVER_PATTERN.match(__version__), (
        f"rp.__version__={__version__!r} is not a valid semver. "
        f"This likely means the version-resolution code is reading a git "
        f"branch/tag ref instead of the package version."
    )


def test_version_is_not_a_git_ref():
    """__version__ must never be a git branch/ref name."""
    assert __version__.lower() not in GIT_REF_BLOCKLIST, (
        f"rp.__version__={__version__!r} looks like a git ref, not a "
        f"semver. The agent enroll/heartbeat payload would pollute the "
        f"fleet dashboard with this value."
    )


def test_version_matches_pyproject():
    """__init__.py and pyproject.toml versions must stay in lock-step.

    Without this, bumping one and forgetting the other lets the agent
    install with version A while heartbeats report version B.
    """
    pyproject_path = (
        Path(__file__).resolve().parent.parent / "pyproject.toml"
    )
    with pyproject_path.open("rb") as f:
        data = tomllib.load(f)
    pyproject_version = data["project"]["version"]
    assert __version__ == pyproject_version, (
        f"Version drift: rp.__version__={__version__!r} but "
        f"pyproject.toml version={pyproject_version!r}. Update both."
    )


def test_heartbeat_metrics_report_semver():
    """The heartbeat payload must carry a semver, never a git ref.

    This is the exact code path that POSTs to /v1/heartbeat, so any
    regression here is what would re-introduce 'agent_version=main' on
    the dashboard.
    """
    collector = MetricsCollector()
    metrics = collector.collect_heartbeat_metrics()

    reported = metrics.get("agent_version")
    assert isinstance(reported, str) and reported, (
        "heartbeat metrics missing a non-empty agent_version"
    )
    assert reported.lower() not in GIT_REF_BLOCKLIST, (
        f"heartbeat agent_version={reported!r} is a git ref, not a semver"
    )
    assert SEMVER_PATTERN.match(reported), (
        f"heartbeat agent_version={reported!r} is not a valid semver"
    )


@pytest.mark.parametrize(
    "bad_value", ["main", "master", "HEAD", "latest", "develop"]
)
def test_blocklist_rejects_known_git_refs(bad_value):
    """Sanity check the blocklist itself catches the historical regressions."""
    assert bad_value.lower() in GIT_REF_BLOCKLIST
