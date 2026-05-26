#!/bin/sh
# Remote-Pulse install bootstrap wrapper
#
# Enables the canonical curl-pipe pattern:
#
#     curl -fsSL https://rp.monxas.casa/install | sh -s -- --token=<JWT>
#
# The "real" installer (scripts/install.sh) requires sibling files at
# packaging/{linux,macos}/{install-{systemd,launchd}.sh, *.service, *.plist}.
# That multi-file layout cannot be delivered through a single curl pipe, so
# this wrapper:
#
#   1. If invoked from a local checkout (scripts/install.sh adjacent and
#      ../packaging/ present), exec's the real installer directly.
#   2. Otherwise, downloads a release tarball from
#      ${RP_INSTALL_BASE}/install/rp-install-${RP_VERSION}.tar.gz, verifies
#      its SHA256 against the sibling .sha256 file, extracts to a temp dir,
#      and exec's the bundled scripts/install.sh with the original flags.
#
# POSIX sh, no bash-isms. Tested with dash/ash/bash/zsh.

set -eu

RP_INSTALL_BASE="${RP_INSTALL_BASE:-https://rp.monxas.casa}"
RP_VERSION="${RP_VERSION:-latest}"

TARBALL="rp-install-${RP_VERSION}.tar.gz"
URL="${RP_INSTALL_BASE}/install/${TARBALL}"
SHA_URL="${URL}.sha256"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log()  { printf '\033[1;34m→\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mWARN:\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; }

print_help() {
    cat <<'EOF'
Remote-Pulse install bootstrap

Usage:
  install-bootstrap.sh [--token=JWT] [--server=URL] [--group=NAME]
                       [--hostname=HOST] [--version=REF]
                       [--show] [--dry-run] [--help]

Behaviour:
  If invoked from a local checkout (scripts/install.sh and ../packaging/
  present), exec's the local installer directly. Otherwise downloads and
  verifies a release tarball, then exec's the bundled installer.

Env vars:
  RP_INSTALL_BASE   Base URL for the tarball + sha256 (default:
                    https://rp.monxas.casa)
  RP_VERSION        Tarball version to fetch (default: latest).
                    Resolves to rp-install-<RP_VERSION>.tar.gz.
  RP_TOKEN, RP_SERVER, RP_GROUP, RP_HOSTNAME — forwarded to installer.

All other flags are passed through unchanged to scripts/install.sh.
EOF
}

need() {
    cmd=$1
    if ! command -v "$cmd" >/dev/null 2>&1; then
        err "missing required command: $cmd"
        exit 1
    fi
}

sha256_of() {
    file=$1
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$file" | awk '{print $1}'
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$file" | awk '{print $1}'
    else
        err "no sha256 tool (sha256sum or shasum) found"
        exit 1
    fi
}

# ---------------------------------------------------------------------------
# --help is handled here too so users can sanity-check the wrapper without
# triggering a download. Everything else is forwarded.
# ---------------------------------------------------------------------------
for arg in "$@"; do
    case "$arg" in
        -h|--help)
            print_help
            exit 0
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Local checkout fast-path
# ---------------------------------------------------------------------------
# `dirname "$0"` is not meaningful when this wrapper is piped through stdin
# (sh sets $0 to "sh"), so the cd may fail — that's fine, we fall through to
# the download path.
SCRIPT_DIR=""
if [ -n "${0:-}" ] && [ "$0" != "sh" ] && [ "$0" != "-sh" ] && [ "$0" != "bash" ]; then
    SCRIPT_DIR=$(cd "$(dirname -- "$0")" 2>/dev/null && pwd) || SCRIPT_DIR=""
fi

if [ -n "$SCRIPT_DIR" ] \
    && [ -f "$SCRIPT_DIR/install.sh" ] \
    && [ -d "$SCRIPT_DIR/../packaging/linux" ] \
    && [ -d "$SCRIPT_DIR/../packaging/macos" ]; then
    log "Local checkout detected at $SCRIPT_DIR — exec'ing install.sh directly"
    exec sh "$SCRIPT_DIR/install.sh" "$@"
fi

# ---------------------------------------------------------------------------
# Remote download path
# ---------------------------------------------------------------------------
need curl
need tar

TMP=$(mktemp -d 2>/dev/null || mktemp -d -t rp-install)
# shellcheck disable=SC2064
trap "rm -rf '$TMP'" EXIT INT TERM

log "Downloading $URL"
if ! curl -fsSL "$URL" -o "$TMP/$TARBALL"; then
    err "failed to download $URL"
    exit 1
fi

log "Fetching SHA256 from $SHA_URL"
SHA_RAW=$(curl -fsSL "$SHA_URL") || {
    err "failed to fetch $SHA_URL"
    exit 1
}
EXPECTED=$(printf '%s\n' "$SHA_RAW" | awk '{print $1}' | head -n1)
if [ -z "$EXPECTED" ]; then
    err "could not parse expected SHA256 from $SHA_URL"
    exit 1
fi

ACTUAL=$(sha256_of "$TMP/$TARBALL")
if [ "$EXPECTED" != "$ACTUAL" ]; then
    err "SHA256 mismatch for $TARBALL"
    err "  expected: $EXPECTED"
    err "  actual:   $ACTUAL"
    exit 1
fi
log "SHA256 verified: $ACTUAL"

log "Extracting $TARBALL"
tar -xzf "$TMP/$TARBALL" -C "$TMP"

INSTALLER="$TMP/scripts/install.sh"
if [ ! -f "$INSTALLER" ]; then
    err "tarball does not contain scripts/install.sh"
    exit 1
fi
if [ ! -d "$TMP/packaging/linux" ] || [ ! -d "$TMP/packaging/macos" ]; then
    err "tarball is missing packaging/{linux,macos}/"
    exit 1
fi

chmod +x "$INSTALLER" 2>/dev/null || true
log "Handing off to $(basename "$INSTALLER")"
exec sh "$INSTALLER" "$@"
