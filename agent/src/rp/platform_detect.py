"""Cross-platform OS, architecture, and capability detection."""

import hashlib
import platform
import subprocess
import sys
from pathlib import Path
from typing import Optional

import structlog

logger = structlog.get_logger()


def get_os() -> str:
    """Get normalized OS name."""
    system = platform.system().lower()
    if system == "darwin":
        return "macos"
    return system


def get_arch() -> str:
    """Get normalized architecture."""
    machine = platform.machine().lower()
    if machine in ("amd64", "x86_64"):
        return "x86_64"
    if machine in ("arm64", "aarch64"):
        return "arm64"
    return machine


def get_distro() -> Optional[str]:
    """Get distribution name and version."""
    os_type = get_os()

    if os_type == "linux":
        # Try os-release first (systemd standard)
        os_release = Path("/etc/os-release")
        if os_release.exists():
            data = {}
            for line in os_release.read_text().splitlines():
                if "=" in line:
                    key, value = line.split("=", 1)
                    data[key] = value.strip('"')

            name = data.get("ID", "unknown")
            version = data.get("VERSION_ID", "")
            return f"{name}-{version}" if version else name

        # Fallback to platform
        return platform.platform()

    elif os_type == "macos":
        return f"macos-{platform.mac_ver()[0]}"

    elif os_type == "windows":
        return f"win-{platform.win32_ver()[0]}"

    return None


def get_kernel() -> str:
    """Get kernel version."""
    return platform.release()


def get_fqdn() -> str:
    """Get fully qualified domain name."""
    return platform.node()


def get_host_fingerprint() -> str:
    """
    Generate stable host fingerprint from machine ID.

    - Linux: /etc/machine-id
    - macOS: IOPlatformUUID
    - Windows: MachineGuid registry key
    """
    os_type = get_os()

    try:
        if os_type == "linux":
            machine_id = Path("/etc/machine-id").read_text().strip()
            if not machine_id:
                machine_id = Path("/var/lib/dbus/machine-id").read_text().strip()
            return hashlib.sha256(machine_id.encode()).hexdigest()

        elif os_type == "macos":
            result = subprocess.run(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                capture_output=True,
                text=True,
                check=True
            )
            for line in result.stdout.splitlines():
                if "IOPlatformUUID" in line:
                    uuid = line.split('"')[3]
                    return hashlib.sha256(uuid.encode()).hexdigest()
            raise RuntimeError("IOPlatformUUID not found")

        elif os_type == "windows":
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography"
            )
            guid, _ = winreg.QueryValueEx(key, "MachineGuid")
            winreg.CloseKey(key)
            return hashlib.sha256(guid.encode()).hexdigest()

    except Exception as e:
        logger.warning("failed to get stable machine ID, using fallback", error=str(e))
        # Fallback: hash of hostname + some system info
        fallback = f"{platform.node()}-{platform.machine()}-{platform.system()}"
        return hashlib.sha256(fallback.encode()).hexdigest()

    return hashlib.sha256(platform.node().encode()).hexdigest()


def detect_capabilities() -> dict[str, bool]:
    """Detect optional capabilities on this host."""
    caps = {}

    # Check for nvidia-smi (GPU support)
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            timeout=2
        )
        caps["nvidia_gpu"] = result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        caps["nvidia_gpu"] = False

    # Check for systemd
    caps["systemd"] = Path("/run/systemd/system").exists()

    # Check for docker
    try:
        result = subprocess.run(["docker", "info"], capture_output=True, timeout=2)
        caps["docker"] = result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        caps["docker"] = False

    return caps


def get_platform_info() -> dict[str, any]:
    """Get complete platform information."""
    return {
        "os": get_os(),
        "arch": get_arch(),
        "distro": get_distro(),
        "kernel": get_kernel(),
        "fqdn": get_fqdn(),
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "capabilities": detect_capabilities(),
    }
