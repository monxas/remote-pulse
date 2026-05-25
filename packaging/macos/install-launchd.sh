#!/usr/bin/env sh
# install-launchd.sh — Idempotent installer for the Remote-Pulse launchd plist.
# Part of F1-5 (ADR-0008). Runs as a LaunchDaemon (system-wide).
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST="$SCRIPT_DIR/com.monxas.remote-pulse.plist"

[ -f "$PLIST" ] || { echo "ERROR: $PLIST no existe" >&2; exit 1; }

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: este script debe ejecutarse como root (sudo)." >&2
    exit 1
fi

# Detect rp binary
RP_BIN=""
for candidate in /usr/local/bin/rp /opt/homebrew/bin/rp "$HOME/.local/bin/rp"; do
    [ -x "$candidate" ] && RP_BIN="$candidate" && break
done
[ -z "$RP_BIN" ] && { echo "ERROR: rp not found" >&2; exit 1; }

TMP_PLIST=$(mktemp)
sed "s|/usr/local/bin/rp|$RP_BIN|" "$PLIST" > "$TMP_PLIST"

mkdir -p /var/log/rp /var/lib/rp /etc/rp

DEST="/Library/LaunchDaemons/com.monxas.remote-pulse.plist"

# Si ya está cargado, descargar antes de reinstalar (idempotencia)
if launchctl print system/com.monxas.remote-pulse >/dev/null 2>&1; then
    launchctl bootout system "$DEST" 2>/dev/null || true
fi

install -m 644 -o root -g wheel "$TMP_PLIST" "$DEST"
rm -f "$TMP_PLIST"

launchctl bootstrap system "$DEST"
launchctl enable system/com.monxas.remote-pulse

echo "OK launchd plist installed."
echo "    Inspect: sudo launchctl print system/com.monxas.remote-pulse"
echo "    Logs:    tail -f /var/log/rp/stdout.log /var/log/rp/stderr.log"
