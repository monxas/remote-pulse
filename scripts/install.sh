#!/usr/bin/env sh
# Remote-Pulse bootstrap installer (F1 — ADR-0008)
# SHA256: <auto-injected en F7 build pipeline>
#
# Idempotent POSIX sh installer. Runs on bash/dash/ash/sh.
# Companion scripts in lib/ provide OS detection and dependency installers.

set -eu

# ---------------------------------------------------------------------------
# Defaults (overridable via env or flags)
# ---------------------------------------------------------------------------
RP_SERVER="${RP_SERVER:-http://localhost:8080}"
RP_TOKEN="${RP_TOKEN:-}"
RP_GROUP="${RP_GROUP:-default}"
RP_HOSTNAME="${RP_HOSTNAME:-$(hostname -s 2>/dev/null || hostname)}"
RP_VERSION="${RP_VERSION:-latest}"
SHOW_MODE=0
DRY_RUN=0

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LIB_DIR="$SCRIPT_DIR/lib"
PACKAGING_DIR="$SCRIPT_DIR/../packaging"
# Per-OS service installer locations (resolved at runtime below).
PACKAGING_LINUX_DIR="$PACKAGING_DIR/linux"
PACKAGING_MACOS_DIR="$PACKAGING_DIR/macos"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log()  { printf '\033[1;34m→\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mWARN:\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; }
ok()   { printf '\033[1;32m✓\033[0m %s\n' "$*"; }

print_help() {
    cat <<'EOF'
Remote-Pulse installer (F1)

Usage:
  install.sh [--token=JWT] [--server=URL] [--group=NAME]
             [--hostname=HOST] [--version=REF] [--show] [--help]

Flags:
  --token=JWT       Enrollment token (required unless --show). Env: RP_TOKEN
  --server=URL      Remote-Pulse server. Default: http://localhost:8080
  --group=NAME      Host group. Default: "default"
  --hostname=HOST   Override hostname for enrollment. Default: $(hostname -s)
  --version=REF     Agent version / git ref to install. Default: "latest"
  --show            Print plan and SHA256 instead of executing.
  --dry-run         Run installer but skip mutating steps (service unit, enroll, config write).
                    Useful for smoke-testing path resolution / OS detection.
  -h, --help        Show this help.

Env vars equivalent to flags:
  RP_SERVER, RP_TOKEN, RP_GROUP, RP_HOSTNAME, RP_VERSION

Examples:
  # Audit-first
  sh install.sh --show

  # Token-driven (silent install)
  sh install.sh --token=eyJhbGc... --group=family

TODO (later phases):
  F2: install Tailscale + enroll via tailnet auth-key
  F4: SSH keygen + push to server
  F7: replace dev install with PyInstaller binary + SHA256 verify
EOF
}

# ---------------------------------------------------------------------------
# Parse flags
# ---------------------------------------------------------------------------
while [ $# -gt 0 ]; do
    case "$1" in
        --token=*)    RP_TOKEN="${1#*=}" ;;
        --server=*)   RP_SERVER="${1#*=}" ;;
        --group=*)    RP_GROUP="${1#*=}" ;;
        --hostname=*) RP_HOSTNAME="${1#*=}" ;;
        --version=*)  RP_VERSION="${1#*=}" ;;
        --show)       SHOW_MODE=1 ;;
        --dry-run)    DRY_RUN=1 ;;
        -h|--help)    print_help; exit 0 ;;
        *) err "Unknown flag: $1"; print_help >&2; exit 2 ;;
    esac
    shift
done

# ---------------------------------------------------------------------------
# Load lib helpers (best-effort; fallback to inline detection)
# ---------------------------------------------------------------------------
if [ -r "$LIB_DIR/detect-os.sh" ]; then
    # shellcheck source=lib/detect-os.sh
    . "$LIB_DIR/detect-os.sh"
else
    detect_os()   { uname -s | tr '[:upper:]' '[:lower:]'; }
    detect_arch() { uname -m; }
fi

OS="$(detect_os)"
ARCH_RAW="$(detect_arch)"
case "$ARCH_RAW" in
    x86_64|amd64) ARCH=x64 ;;
    aarch64|arm64) ARCH=arm64 ;;
    *) err "arch $ARCH_RAW no soportada"; exit 1 ;;
esac

# ---------------------------------------------------------------------------
# --show mode: dry-run plan
# ---------------------------------------------------------------------------
if [ "$SHOW_MODE" = "1" ]; then
    cat <<EOF
Remote-Pulse installer plan
===========================

This installer will:
  1. Detect OS/arch ($(uname -s) $(uname -m) → $OS/$ARCH)
  2. Install uv if missing (https://astral.sh/uv)
  3. Install Python 3.12 if missing (apt-get / dnf / brew)
  4. Install remote-pulse agent (uv tool install, ref=$RP_VERSION)
       F7 TODO: replace with PyInstaller binary + SHA256 verify
  5. POST $RP_SERVER/v1/enroll with provided token
       F2 TODO: server returns Tailscale auth-key, agent joins tailnet
  6. Write /etc/rp/config.toml (root:root 0600)
  7. Install service unit (systemd or launchd)
  8. Start the service

Target:
  Server:   $RP_SERVER
  Hostname: $RP_HOSTNAME
  Group:    $RP_GROUP
  Version:  $RP_VERSION

Inspect SHA256: <published in F7 at $RP_SERVER/install.sha256>
EOF
    exit 0
fi

# ---------------------------------------------------------------------------
# --dry-run mode: validate paths + OS without root / token / network mutations
# ---------------------------------------------------------------------------
if [ "$DRY_RUN" = "1" ]; then
    log "[dry-run] OS=$OS ARCH=$ARCH"
    case "$OS" in
        linux)
            DRY_SVC="$PACKAGING_LINUX_DIR/install-systemd.sh"
            DRY_UNIT="$PACKAGING_LINUX_DIR/remote-pulse.service"
            ;;
        darwin)
            DRY_SVC="$PACKAGING_MACOS_DIR/install-launchd.sh"
            DRY_UNIT="$PACKAGING_MACOS_DIR/com.monxas.remote-pulse.plist"
            ;;
        *)
            err "[dry-run] Unsupported OS: $OS"
            exit 1
            ;;
    esac
    log "[dry-run] Service installer: $DRY_SVC"
    log "[dry-run] Service unit/plist: $DRY_UNIT"
    if [ ! -x "$DRY_SVC" ]; then
        err "[dry-run] FAIL: service installer not executable at $DRY_SVC"
        exit 1
    fi
    if [ ! -f "$DRY_UNIT" ]; then
        err "[dry-run] FAIL: service unit/plist not found at $DRY_UNIT"
        exit 1
    fi
    ok "[dry-run] All persistence assets resolved correctly."
    exit 0
fi

# ---------------------------------------------------------------------------
# Validate required input
# ---------------------------------------------------------------------------
if [ -z "$RP_TOKEN" ]; then
    err "--token=<JWT> requerido (o env RP_TOKEN). Run with --show to inspect plan."
    exit 1
fi

# Need curl for enroll + uv installer
if ! command -v curl >/dev/null 2>&1; then
    err "curl not found. Install curl and re-run."
    exit 1
fi

# sudo helper (no-op if already root)
if [ "$(id -u)" = "0" ]; then
    SUDO=""
else
    if command -v sudo >/dev/null 2>&1; then
        SUDO="sudo"
    else
        err "Need root or sudo to write /etc/rp and install service unit."
        exit 1
    fi
fi

# ---------------------------------------------------------------------------
# 1. Ensure Python 3.12
# ---------------------------------------------------------------------------
if [ -r "$LIB_DIR/install-python.sh" ]; then
    # shellcheck source=lib/install-python.sh
    . "$LIB_DIR/install-python.sh"
    ensure_python_312 || warn "Python install helper failed; uv will manage its own."
else
    warn "lib/install-python.sh missing; uv will manage Python if needed."
fi

# ---------------------------------------------------------------------------
# 2. Ensure uv
# ---------------------------------------------------------------------------
if [ -r "$LIB_DIR/install-uv.sh" ]; then
    # shellcheck source=lib/install-uv.sh
    . "$LIB_DIR/install-uv.sh"
    ensure_uv
else
    if ! command -v uv >/dev/null 2>&1; then
        log "Installing uv..."
        curl -fsSL https://astral.sh/uv/install.sh | sh
    fi
fi

# Make sure uv is on PATH in this shell
if [ -d "$HOME/.local/bin" ]; then
    PATH="$HOME/.local/bin:$PATH"
    export PATH
fi

if ! command -v uv >/dev/null 2>&1; then
    err "uv install failed or not on PATH. Try: export PATH=\$HOME/.local/bin:\$PATH"
    exit 1
fi

# ---------------------------------------------------------------------------
# 3. Install remote-pulse agent
# ---------------------------------------------------------------------------
log "Installing remote-pulse agent (ref=$RP_VERSION)..."
DEV_AGENT="/Users/ramonkamibayashicarrera/monxas-remote-pulse/agent"
INSTALL_OK=0

# Try GitHub install first (will succeed once repo is public, post-F7)
if uv tool install --quiet --reinstall \
        --from "git+https://github.com/monxas/remote-pulse.git@${RP_VERSION}#subdirectory=agent" \
        remote-pulse 2>/dev/null; then
    INSTALL_OK=1
else
    warn "GitHub install failed (repo not public yet)."
    if [ -d "$DEV_AGENT" ]; then
        log "Dev fallback: installing from local path $DEV_AGENT"
        if uv tool install --quiet --reinstall --from "$DEV_AGENT" remote-pulse; then
            INSTALL_OK=1
        fi
    fi
fi

if [ "$INSTALL_OK" != "1" ]; then
    err "Cannot install agent. Provide --version=<git-ref> or run on dev host."
    exit 1
fi

# ---------------------------------------------------------------------------
# 4. Enroll with server
# ---------------------------------------------------------------------------
log "Enrolling with $RP_SERVER..."

# Stable per-host fingerprint (Linux: /etc/machine-id; macOS: IOPlatformUUID)
HOST_FINGERPRINT=""
if [ -r /etc/machine-id ]; then
    HOST_FINGERPRINT="$(cat /etc/machine-id | tr -d '\n' | shasum -a 256 2>/dev/null | cut -d' ' -f1 \
                       || cat /etc/machine-id | tr -d '\n' | sha256sum | cut -d' ' -f1)"
elif command -v ioreg >/dev/null 2>&1; then
    HOST_FINGERPRINT="$(ioreg -rd1 -c IOPlatformExpertDevice 2>/dev/null \
                       | awk -F'"' '/IOPlatformUUID/{print $4}' \
                       | shasum -a 256 | cut -d' ' -f1)"
fi
if [ -z "$HOST_FINGERPRINT" ]; then
    HOST_FINGERPRINT="unknown-$(date +%s)"
fi

ENROLL_PAYLOAD="$(printf '{"token":"%s","hostname":"%s","group":"%s","host_fingerprint":"%s","os":"%s","arch":"%s","agent_version":"%s"}' \
    "$RP_TOKEN" "$RP_HOSTNAME" "$RP_GROUP" "$HOST_FINGERPRINT" "$OS" "$ARCH" "${RP_VERSION:-main}")"

ENROLL_RESP="$(curl -fsSL -X POST "$RP_SERVER/v1/enroll" \
    -H "Content-Type: application/json" \
    -d "$ENROLL_PAYLOAD")" || {
    err "Enrollment failed against $RP_SERVER/v1/enroll"
    exit 1
}

# Parse host_id (prefer python3, fallback to grep)
HOST_ID=""
if command -v python3 >/dev/null 2>&1; then
    HOST_ID="$(printf '%s' "$ENROLL_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('host_id',''))")"
fi
if [ -z "$HOST_ID" ]; then
    # crude fallback for environments without python3 (shouldn't happen post-step-1)
    HOST_ID="$(printf '%s' "$ENROLL_RESP" | sed -n 's/.*"host_id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
fi
if [ -z "$HOST_ID" ]; then
    err "Could not parse host_id from enroll response: $ENROLL_RESP"
    exit 1
fi

# ---------------------------------------------------------------------------
# 5. Write config
# ---------------------------------------------------------------------------
log "Writing /etc/rp/config.toml..."
$SUDO mkdir -p /etc/rp /var/lib/rp
$SUDO tee /etc/rp/config.toml >/dev/null <<EOF
host_id = "$HOST_ID"
server_url = "$RP_SERVER"
hostname = "$RP_HOSTNAME"
group = "$RP_GROUP"
heartbeat_interval_s = 30
EOF
$SUDO chown -R root:root /etc/rp /var/lib/rp 2>/dev/null || \
    $SUDO chown -R 0:0 /etc/rp /var/lib/rp
$SUDO chmod 600 /etc/rp/config.toml

# ---------------------------------------------------------------------------
# 6. Install service unit (persistent: systemd unit on Linux, launchd plist on macOS)
# ---------------------------------------------------------------------------
SERVICE_INSTALL_RC=0
if [ "$OS" = "linux" ]; then
    SERVICE_INSTALLER="$PACKAGING_LINUX_DIR/install-systemd.sh"
    if [ ! -x "$SERVICE_INSTALLER" ]; then
        err "packaging/linux/install-systemd.sh missing or not executable at $SERVICE_INSTALLER"
        err "Repo layout broken — service unit will NOT be installed. Aborting."
        exit 1
    fi
    if [ "$DRY_RUN" = "1" ]; then
        log "[dry-run] Would invoke: $SUDO $SERVICE_INSTALLER"
    else
        log "Installing systemd unit (persistent service via $SERVICE_INSTALLER)..."
        if ! $SUDO "$SERVICE_INSTALLER"; then
            SERVICE_INSTALL_RC=$?
            err "systemd unit install failed (exit=$SERVICE_INSTALL_RC)."
            err "Recent logs: journalctl -u remote-pulse.service -n 50 --no-pager"
            exit 1
        fi
    fi
elif [ "$OS" = "darwin" ]; then
    SERVICE_INSTALLER="$PACKAGING_MACOS_DIR/install-launchd.sh"
    if [ ! -x "$SERVICE_INSTALLER" ]; then
        err "packaging/macos/install-launchd.sh missing or not executable at $SERVICE_INSTALLER"
        err "Repo layout broken — launchd plist will NOT be installed. Aborting."
        exit 1
    fi
    if [ "$DRY_RUN" = "1" ]; then
        log "[dry-run] Would invoke: $SUDO $SERVICE_INSTALLER"
    else
        log "Installing launchd plist (persistent service via $SERVICE_INSTALLER)..."
        if ! $SUDO "$SERVICE_INSTALLER"; then
            SERVICE_INSTALL_RC=$?
            err "launchd plist install failed (exit=$SERVICE_INSTALL_RC)."
            err "Inspect: sudo launchctl print system/com.monxas.remote-pulse"
            err "Logs:    tail -f /var/log/rp/stderr.log /var/log/rp/stdout.log"
            exit 1
        fi
    fi
else
    warn "Unsupported OS for service install: $OS (no systemd/launchd persistence configured)"
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
ok "Remote-Pulse installed."
echo "  Host:     $RP_HOSTNAME"
echo "  Group:    $RP_GROUP"
echo "  Server:   $RP_SERVER"
echo "  Host ID:  $HOST_ID"
echo ""
echo "  Local CLI:  rp status"
echo "  Dashboard:  $RP_SERVER/dash (available after F5)"
echo ""
echo "  Uninstall:  sh $(dirname "$0")/uninstall.sh --confirm"
