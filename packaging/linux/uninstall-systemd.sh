#!/usr/bin/env sh
# uninstall-systemd.sh — Stop, disable and remove the Remote-Pulse systemd unit.
# Idempotent: succeeds even if the unit is already absent.
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: este script debe ejecutarse como root (sudo)." >&2
    exit 1
fi

systemctl stop remote-pulse.service 2>/dev/null || true
systemctl disable remote-pulse.service 2>/dev/null || true
rm -f /etc/systemd/system/remote-pulse.service
rm -f /etc/logrotate.d/remote-pulse
systemctl daemon-reload

echo "OK systemd unit removed."
echo "NOTE: /etc/rp /var/lib/rp /var/log/rp NO se borran (data preserved)."
echo "      Borra manualmente si quieres limpieza total."
