#!/usr/bin/env sh
# uninstall-launchd.sh — Stop and remove the Remote-Pulse launchd plist.
# Idempotent.
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: este script debe ejecutarse como root (sudo)." >&2
    exit 1
fi

DEST="/Library/LaunchDaemons/com.monxas.remote-pulse.plist"

if launchctl print system/com.monxas.remote-pulse >/dev/null 2>&1; then
    launchctl bootout system "$DEST" 2>/dev/null || true
fi

launchctl disable system/com.monxas.remote-pulse 2>/dev/null || true
rm -f "$DEST"

echo "OK launchd plist removed."
echo "NOTE: /etc/rp /var/lib/rp /var/log/rp NO se borran (data preserved)."
