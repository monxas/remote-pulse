#!/usr/bin/env sh
# install-systemd.sh — Idempotent installer for the Remote-Pulse systemd unit.
# Part of F1-5 (ADR-0008). Invoked by scripts/install.sh on Linux hosts.
#
# Drops /etc/systemd/system/remote-pulse.service, daemon-reloads, enables,
# and starts the service. Re-running this script is safe (idempotent):
#   - existing service is stopped before unit file is overwritten
#   - enable --now is no-op when already enabled+active
#
# F4: Supports --with-keys-sync flag to install SSH key sync timer
set -eu

# -------- Parse flags --------
WITH_KEYS_SYNC=0
DRY_RUN=0
for arg in "$@"; do
    case "$arg" in
        --with-keys-sync) WITH_KEYS_SYNC=1 ;;
        --dry-run)        DRY_RUN=1 ;;
        -h|--help)
            cat <<'EOF'
install-systemd.sh — Drop and start remote-pulse.service.

Usage:
  install-systemd.sh [--with-keys-sync] [--dry-run]

Flags:
  --with-keys-sync  Also install remote-pulse-keys-sync.timer (F4 SSH key sync).
  --dry-run         Print actions without writing files / touching systemd.
  -h, --help        This help.
EOF
            exit 0
            ;;
        *) echo "Unknown flag: $arg" >&2; exit 1 ;;
    esac
done

log() { printf '[install-systemd] %s\n' "$*"; }
err() { printf '[install-systemd] ERROR: %s\n' "$*" >&2; }

# -------- Locate source unit file --------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
UNIT_FILE="$SCRIPT_DIR/remote-pulse.service"
DEST_UNIT="/etc/systemd/system/remote-pulse.service"

[ -f "$UNIT_FILE" ] || { err "$UNIT_FILE no existe"; exit 1; }

# -------- Preflight: require root (unless dry-run) --------
if [ "$DRY_RUN" = "0" ] && [ "$(id -u)" -ne 0 ]; then
    err "este script debe ejecutarse como root (sudo)."
    exit 1
fi

# -------- Preflight: require systemd (PID 1 must be systemd) --------
if ! command -v systemctl >/dev/null 2>&1; then
    if [ "$DRY_RUN" = "1" ]; then
        log "[dry-run] systemctl ausente (probable build host no-Linux) — saltando preflight."
    else
        err "systemctl no encontrado — sistema sin systemd no soportado."
        err "(chroot? container sin init? Instala systemd o usa rp en modo foreground.)"
        exit 1
    fi
elif [ -d /run/systemd/system ]; then
    : # systemd is running as init
elif [ "$DRY_RUN" = "1" ]; then
    log "[dry-run] /run/systemd/system ausente — sería un error en run real."
else
    err "/run/systemd/system no existe — systemd no está corriendo como PID 1."
    err "(Build container? Run real Linux host or use --dry-run to validate paths.)"
    exit 1
fi

# -------- Detect rp binary path --------
RP_BIN=""
for candidate in /root/.local/bin/rp /usr/local/bin/rp /usr/bin/rp /opt/rp/bin/rp; do
    [ -x "$candidate" ] && RP_BIN="$candidate" && break
done
if [ -z "$RP_BIN" ]; then
    if [ "$DRY_RUN" = "1" ]; then
        log "[dry-run] rp binary not found — would fail in real run."
        RP_BIN="/usr/local/bin/rp"
    else
        err "rp binary not found in PATH (checked /root/.local/bin, /usr/local/bin, /usr/bin, /opt/rp/bin)"
        exit 1
    fi
fi
log "rp binary: $RP_BIN"

# -------- Build patched unit (substitute ExecStart path) --------
TMP_UNIT=$(mktemp)
trap 'rm -f "$TMP_UNIT"' EXIT
sed "s|/root/.local/bin/rp|$RP_BIN|g" "$UNIT_FILE" > "$TMP_UNIT"

if [ "$DRY_RUN" = "1" ]; then
    log "[dry-run] Would install $DEST_UNIT (mode 644) with ExecStart=$RP_BIN heartbeat --daemon"
    log "[dry-run] Would run: systemctl daemon-reload && systemctl enable --now remote-pulse.service"
    if [ "$WITH_KEYS_SYNC" -eq 1 ]; then
        log "[dry-run] Would install remote-pulse-keys-sync.{service,timer} and enable timer"
    fi
    log "[dry-run] OK"
    exit 0
fi

# -------- Idempotency: stop service first if currently running, before
# overwriting the unit file. systemctl restart later re-loads with new content.
if systemctl is-active --quiet remote-pulse.service 2>/dev/null; then
    log "remote-pulse.service active — stopping before re-install (idempotent)."
    systemctl stop remote-pulse.service || true
fi

# -------- Install unit file --------
install -m 644 "$TMP_UNIT" "$DEST_UNIT"
log "unit installed: $DEST_UNIT"

mkdir -p /etc/rp /var/lib/rp /var/log/rp

# -------- Logrotate (idempotent) --------
LOGROTATE_SRC="$SCRIPT_DIR/logrotate.conf"
if [ -f "$LOGROTATE_SRC" ] && [ -d /etc/logrotate.d ]; then
    install -m 644 "$LOGROTATE_SRC" /etc/logrotate.d/remote-pulse
    log "logrotate config installed"
fi

# -------- daemon-reload + enable + start --------
systemctl daemon-reload
systemctl enable --now remote-pulse.service

# -------- Verify --------
if systemctl is-active --quiet remote-pulse.service; then
    log "OK service active."
else
    err "service did not enter active state."
    err "Recent logs:"
    journalctl -u remote-pulse.service -n 50 --no-pager >&2 || true
    exit 1
fi

# -------- Optional keys-sync timer (F4) --------
if [ "$WITH_KEYS_SYNC" -eq 1 ]; then
    KEYS_SYNC_SERVICE="$SCRIPT_DIR/remote-pulse-keys-sync.service"
    KEYS_SYNC_TIMER="$SCRIPT_DIR/remote-pulse-keys-sync.timer"

    if [ -f "$KEYS_SYNC_SERVICE" ] && [ -f "$KEYS_SYNC_TIMER" ]; then
        install -m 644 "$KEYS_SYNC_SERVICE" /etc/systemd/system/remote-pulse-keys-sync.service
        install -m 644 "$KEYS_SYNC_TIMER" /etc/systemd/system/remote-pulse-keys-sync.timer
        systemctl daemon-reload
        systemctl enable --now remote-pulse-keys-sync.timer
        log "OK SSH key sync timer installed and enabled."
    else
        err "keys-sync systemd units not found, skipping"
    fi
fi

echo "OK systemd unit installed and started."
systemctl status --no-pager remote-pulse.service || true
