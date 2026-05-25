#!/usr/bin/env bash
# Rotate JWT secret for Remote-Pulse server
#
# F8-SECURITY: JWT secret rotation invalidates all pending enrollment tokens.
# Recommended cadence: yearly or after suspected leak.
#
# Usage:
#   sudo ./rotate-jwt-secret.sh
#
# Prerequisites:
#   - Running as root or with sudo
#   - Server config at /etc/rp/server.env
#   - openssl installed

set -euo pipefail

CONFIG_FILE="/etc/rp/server.env"
SERVICE_NAME="remote-pulse-server"

# Check root
if [ "$EUID" -ne 0 ]; then
    echo "Error: Must run as root (use sudo)" >&2
    exit 1
fi

# Check config exists
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: Server config not found at $CONFIG_FILE" >&2
    exit 1
fi

# Generate new HS512 secret (64 bytes = 512 bits)
echo "Generating new JWT secret (64-byte hex, HS512-compatible)..."
NEW_SECRET=$(openssl rand -hex 64)

if [ ${#NEW_SECRET} -lt 32 ]; then
    echo "Error: Generated secret too short (min 32 chars)" >&2
    exit 1
fi

echo "New secret: ${NEW_SECRET:0:16}... (truncated for display)"

# Backup existing config
BACKUP_FILE="${CONFIG_FILE}.backup.$(date +%Y%m%d-%H%M%S)"
cp "$CONFIG_FILE" "$BACKUP_FILE"
echo "Backed up existing config to: $BACKUP_FILE"

# Update JWT_SECRET in config
if grep -q '^JWT_SECRET=' "$CONFIG_FILE"; then
    # Replace existing
    sed -i.tmp "s|^JWT_SECRET=.*|JWT_SECRET=${NEW_SECRET}|" "$CONFIG_FILE"
    rm -f "${CONFIG_FILE}.tmp"
else
    # Append if missing
    echo "JWT_SECRET=${NEW_SECRET}" >> "$CONFIG_FILE"
fi

echo "Updated JWT_SECRET in $CONFIG_FILE"

# Restart server service
if systemctl is-active --quiet "$SERVICE_NAME"; then
    echo "Restarting $SERVICE_NAME..."
    systemctl restart "$SERVICE_NAME"
    echo "Service restarted successfully"
else
    echo "Warning: $SERVICE_NAME not running. Start manually after rotation."
fi

echo ""
echo "✓ JWT secret rotated successfully"
echo ""
echo "IMPORTANT:"
echo "  - All pending enrollment tokens are now INVALID"
echo "  - Re-generate enrollment tokens for any pending enrollments"
echo "  - Enrolled agents are NOT affected (they use Tailscale identity)"
echo "  - Backup config: $BACKUP_FILE"
