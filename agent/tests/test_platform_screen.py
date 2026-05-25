"""Tests for screen capabilities detection in platform_detect."""

from unittest.mock import patch, MagicMock

from rp.platform_detect import detect_screen_capabilities


@patch("rp.platform_detect.get_os")
@patch("shutil.which")
@patch("pathlib.Path.exists")
def test_detect_rustdesk_linux(mock_exists, mock_which, mock_get_os):
    """Test RustDesk detection on Linux."""
    mock_get_os.return_value = "linux"
    mock_which.side_effect = lambda x: "/usr/bin/rustdesk" if x == "rustdesk" else None
    mock_exists.return_value = False

    caps = detect_screen_capabilities()

    assert caps["rustdesk_installed"] is True


@patch("rp.platform_detect.get_os")
@patch("shutil.which")
def test_detect_rustdesk_macos(mock_which, mock_get_os):
    """Test RustDesk detection on macOS."""
    mock_get_os.return_value = "macos"
    mock_which.return_value = None

    with patch("pathlib.Path.exists") as mock_exists:

        def exists_side_effect():
            return True

        mock_exists.return_value = True

        caps = detect_screen_capabilities()

        assert caps["rustdesk_installed"] is True


@patch("rp.platform_detect.get_os")
@patch("shutil.which")
def test_detect_sunshine_windows(mock_which, mock_get_os):
    """Test Sunshine detection on Windows."""
    mock_get_os.return_value = "windows"
    mock_which.return_value = None

    with patch("pathlib.Path.exists") as mock_exists:
        # Return True for Sunshine path, False for RustDesk
        def exists_side_effect():
            return True

        mock_exists.return_value = True

        caps = detect_screen_capabilities()

        assert caps.get("sunshine_installed") is True
        assert "sunshine_admin_url" in caps


@patch("rp.platform_detect.get_os")
@patch("shutil.which")
def test_detect_vnc_linux(mock_which, mock_get_os):
    """Test VNC detection on Linux."""
    mock_get_os.return_value = "linux"
    mock_which.side_effect = lambda x: (
        "/usr/bin/vncserver" if x == "vncserver" else None
    )

    caps = detect_screen_capabilities()

    assert caps.get("vnc_installed") is True


@patch("shutil.which")
@patch("subprocess.run")
def test_detect_tailscale_ssh_enabled(mock_run, mock_which):
    """Test Tailscale SSH enabled detection."""
    mock_which.return_value = "/usr/bin/tailscale"

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = b'{"Self": {"CapMap": {"ssh": true}}}'
    mock_run.return_value = mock_result

    caps = detect_screen_capabilities()

    assert caps.get("tailscale_ssh_enabled") is True


@patch("shutil.which")
def test_detect_tailscale_ssh_not_installed(mock_which):
    """Test Tailscale SSH detection when tailscale not installed."""
    mock_which.return_value = None

    caps = detect_screen_capabilities()

    assert caps.get("tailscale_ssh_enabled") is False


@patch("rp.platform_detect.get_os")
@patch("shutil.which")
@patch("pathlib.Path.exists")
def test_detect_no_capabilities(mock_exists, mock_which, mock_get_os):
    """Test detection when no screen capabilities available."""
    mock_get_os.return_value = "linux"
    mock_which.return_value = None
    mock_exists.return_value = False

    caps = detect_screen_capabilities()

    assert "rustdesk_installed" not in caps
    assert "sunshine_installed" not in caps
    assert "vnc_installed" not in caps
