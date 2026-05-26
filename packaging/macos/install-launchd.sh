#!/usr/bin/env sh
# install-launchd.sh — Idempotent installer for the Remote-Pulse launchd plist.
# Part of F1-5 (ADR-0008). Runs as a LaunchDaemon (system-wide).
#
# Drops /Library/LaunchDaemons/com.monxas.remote-pulse.plist, chowns root:wheel,
# and bootstraps it via launchctl. Falls back to legacy `launchctl load` on
# macOS < 10.10 (or where `bootstrap` is rejected). Re-running this script is
# safe (idempotent) — existing service is booted out before plist overwrite.
set -eu

# -------- Parse flags --------
DRY_RUN=0
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        -h|--help)
            cat <<'EOF'
install-launchd.sh — Drop com.monxas.remote-pulse.plist and bootstrap it.

Usage:
  install-launchd.sh [--dry-run]

Flags:
  --dry-run   Print actions without writing files or invoking launchctl.
  -h, --help  This help.
EOF
            exit 0
            ;;
        *) echo "Unknown flag: $arg" >&2; exit 1 ;;
    esac
done

log() { printf '[install-launchd] %s\n' "$*"; }
err() { printf '[install-launchd] ERROR: %s\n' "$*" >&2; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_SRC="$SCRIPT_DIR/com.monxas.remote-pulse.plist"
LABEL="com.monxas.remote-pulse"
DEST="/Library/LaunchDaemons/${LABEL}.plist"

[ -f "$PLIST_SRC" ] || { err "$PLIST_SRC no existe"; exit 1; }

if [ "$DRY_RUN" = "0" ] && [ "$(id -u)" -ne 0 ]; then
    err "este script debe ejecutarse como root (sudo)."
    exit 1
fi

# Detect rp binary (Homebrew, /usr/local, user-local)
RP_BIN=""
for candidate in /usr/local/bin/rp /opt/homebrew/bin/rp "$HOME/.local/bin/rp"; do
    [ -x "$candidate" ] && RP_BIN="$candidate" && break
done
if [ -z "$RP_BIN" ]; then
    if [ "$DRY_RUN" = "1" ]; then
        log "[dry-run] rp binary not found — would fail in real run."
        RP_BIN="/usr/local/bin/rp"
    else
        err "rp not found (checked /usr/local/bin, /opt/homebrew/bin, ~/.local/bin)"
        exit 1
    fi
fi
log "rp binary: $RP_BIN"

TMP_PLIST=$(mktemp)
trap 'rm -f "$TMP_PLIST"' EXIT
sed "s|/usr/local/bin/rp|$RP_BIN|" "$PLIST_SRC" > "$TMP_PLIST"

if [ "$DRY_RUN" = "1" ]; then
    log "[dry-run] Would install $DEST (root:wheel, mode 644)"
    log "[dry-run] Would run: launchctl bootstrap system $DEST (with launchctl load fallback)"
    log "[dry-run] Would run: launchctl enable system/$LABEL"
    log "[dry-run] OK"
    exit 0
fi

mkdir -p /var/log/rp /var/lib/rp /etc/rp

# -------- Idempotency: bootout existing service before overwriting plist --------
if launchctl print "system/$LABEL" >/dev/null 2>&1; then
    log "$LABEL already loaded — booting out before re-install (idempotent)."
    launchctl bootout system "$DEST" 2>/dev/null || \
        launchctl unload "$DEST" 2>/dev/null || true
fi

install -m 644 -o root -g wheel "$TMP_PLIST" "$DEST"
log "plist installed: $DEST"

# -------- Try modern bootstrap, fall back to legacy load on failure --------
if launchctl bootstrap system "$DEST" 2>/dev/null; then
    log "bootstrap OK (modern launchctl API)"
    launchctl enable "system/$LABEL" 2>/dev/null || true
else
    log "launchctl bootstrap failed — falling back to legacy 'launchctl load'."
    if launchctl load "$DEST"; then
        log "legacy load OK"
    else
        err "both bootstrap and load failed. Inspect: sudo launchctl print system/$LABEL"
        exit 1
    fi
fi

# -------- Verify --------
if launchctl list | grep -q "$LABEL"; then
    log "OK $LABEL is loaded."
else
    err "$LABEL not found in 'launchctl list'."
    err "Logs: /var/log/rp/stderr.log /var/log/rp/stdout.log"
    exit 1
fi

echo "OK launchd plist installed."
echo "    Inspect: sudo launchctl print system/$LABEL"
echo "    Logs:    tail -f /var/log/rp/stdout.log /var/log/rp/stderr.log"
