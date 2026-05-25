#!/usr/bin/env sh
# Remote-Pulse uninstaller (F1 — ADR-0008)
#
# Tears down agent service, removes config/state, and uninstalls the
# `remote-pulse` uv tool. Idempotent — safe to re-run.
#
# Usage:
#   sh uninstall.sh --confirm
#   rp uninstall --confirm     (shells out here)

set -eu

CONFIRM=0
KEEP_TOOL=0

print_help() {
    cat <<'EOF'
Remote-Pulse uninstaller

Usage:
  uninstall.sh --confirm [--keep-tool]

Flags:
  --confirm     Required. Acknowledge destructive operation.
  --keep-tool   Do not run `uv tool uninstall remote-pulse`.
  -h, --help    Show this help.

What it removes:
  - systemd unit (linux) / launchd plist (macos)
  - /etc/rp/config.toml and /etc/rp/
  - /var/lib/rp/ (agent state, SSH keys staging)
  - uv tool `remote-pulse` (unless --keep-tool)

TODO F2: revoke Tailscale node before teardown
TODO F4: revoke SSH keys server-side before teardown
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --confirm)   CONFIRM=1 ;;
        --keep-tool) KEEP_TOOL=1 ;;
        -h|--help)   print_help; exit 0 ;;
        *) echo "Unknown flag: $1" >&2; print_help >&2; exit 2 ;;
    esac
    shift
done

if [ "$CONFIRM" != "1" ]; then
    echo "Refusing to uninstall without --confirm." >&2
    print_help >&2
    exit 1
fi

log()  { printf '\033[1;34m→\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mWARN:\033[0m %s\n' "$*" >&2; }
ok()   { printf '\033[1;32m✓\033[0m %s\n' "$*"; }

if [ "$(id -u)" = "0" ]; then
    SUDO=""
elif command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
else
    warn "No sudo found and not root; some files may not be removable."
    SUDO=""
fi

OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PACKAGING_DIR="$SCRIPT_DIR/../packaging"

# 1. Stop + remove service
if [ "$OS" = "linux" ]; then
    if command -v systemctl >/dev/null 2>&1; then
        log "Stopping systemd unit remote-pulse.service..."
        $SUDO systemctl stop remote-pulse.service 2>/dev/null || true
        $SUDO systemctl disable remote-pulse.service 2>/dev/null || true
    fi
    if [ -x "$PACKAGING_DIR/uninstall-systemd.sh" ]; then
        $SUDO "$PACKAGING_DIR/uninstall-systemd.sh" || warn "systemd unit removal returned non-zero."
    else
        $SUDO rm -f /etc/systemd/system/remote-pulse.service
        $SUDO rm -f /etc/systemd/system/multi-user.target.wants/remote-pulse.service
        if command -v systemctl >/dev/null 2>&1; then
            $SUDO systemctl daemon-reload 2>/dev/null || true
        fi
    fi
elif [ "$OS" = "darwin" ]; then
    log "Unloading launchd plist..."
    $SUDO launchctl unload /Library/LaunchDaemons/casa.monxas.remote-pulse.plist 2>/dev/null || true
    if [ -x "$PACKAGING_DIR/uninstall-launchd.sh" ]; then
        $SUDO "$PACKAGING_DIR/uninstall-launchd.sh" || warn "launchd removal returned non-zero."
    else
        $SUDO rm -f /Library/LaunchDaemons/casa.monxas.remote-pulse.plist
    fi
fi

# 2. Remove config + state
log "Removing /etc/rp and /var/lib/rp..."
$SUDO rm -rf /etc/rp
$SUDO rm -rf /var/lib/rp

# 3. Uninstall uv tool
if [ "$KEEP_TOOL" != "1" ]; then
    if command -v uv >/dev/null 2>&1; then
        log "Uninstalling uv tool remote-pulse..."
        uv tool uninstall remote-pulse 2>/dev/null || warn "uv tool uninstall returned non-zero (maybe not installed)."
    fi
fi

ok "Remote-Pulse uninstalled."
echo ""
echo "TODO (manual):"
echo "  - Revoke enrollment / Tailscale node via:  rp admin hosts (server side)"
echo "  - Remove SSH pubkeys distributed to other hosts (F4)"
