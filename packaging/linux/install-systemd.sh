#!/usr/bin/env sh
# install-systemd.sh — Idempotent installer for the Remote-Pulse systemd unit.
# Part of F1-5 (ADR-0008). Invoked by scripts/install.sh on Linux hosts.
set -eu

# Encuentra el dir del script para localizar el .service
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
UNIT_FILE="$SCRIPT_DIR/remote-pulse.service"

[ -f "$UNIT_FILE" ] || { echo "ERROR: $UNIT_FILE no existe" >&2; exit 1; }

# Requiere root
if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: este script debe ejecutarse como root (sudo)." >&2
    exit 1
fi

# Detect rp binary path (uv tool install ubica en ~/.local/bin/rp o /usr/local/bin/rp)
RP_BIN=""
for candidate in /root/.local/bin/rp /usr/local/bin/rp /usr/bin/rp; do
    [ -x "$candidate" ] && RP_BIN="$candidate" && break
done
[ -z "$RP_BIN" ] && { echo "ERROR: rp binary not found in PATH" >&2; exit 1; }

# Sustituye ExecStart si el path difiere del default
TMP_UNIT=$(mktemp)
sed "s|/root/.local/bin/rp|$RP_BIN|g" "$UNIT_FILE" > "$TMP_UNIT"

install -m 644 "$TMP_UNIT" /etc/systemd/system/remote-pulse.service
rm -f "$TMP_UNIT"

mkdir -p /etc/rp /var/lib/rp /var/log/rp

# Logrotate (idempotente)
LOGROTATE_SRC="$SCRIPT_DIR/logrotate.conf"
if [ -f "$LOGROTATE_SRC" ] && [ -d /etc/logrotate.d ]; then
    install -m 644 "$LOGROTATE_SRC" /etc/logrotate.d/remote-pulse
fi

systemctl daemon-reload
systemctl enable --now remote-pulse.service

echo "OK systemd unit installed and started."
systemctl status --no-pager remote-pulse.service || true
