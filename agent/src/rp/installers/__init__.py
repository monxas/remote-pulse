"""Screen-sharing tool installers (F6-1, F6-2).

Cross-OS installers for RustDesk, Sunshine, and TigerVNC. Each installer
exposes:

- ``detect_installed()``: report whether the tool is present.
- ``install(force=False)``: install or reinstall the tool.
- ``configure(...)``: write rp-managed config in ``/etc/rp/`` and tool-native
  config (e.g. ``RustDesk2.toml``).
- ``uninstall()``: remove tool + clean rp-managed config.

All installers return :class:`InstallResult` dataclasses so the CLI layer can
render uniform success/failure messages.
"""

from rp.installers.base import InstallResult, InstallerError
from rp.installers.rustdesk import RustDeskInstaller
from rp.installers.sunshine import SunshineInstaller
from rp.installers.vnc import VNCInstaller

__all__ = [
    "InstallResult",
    "InstallerError",
    "RustDeskInstaller",
    "SunshineInstaller",
    "VNCInstaller",
]
