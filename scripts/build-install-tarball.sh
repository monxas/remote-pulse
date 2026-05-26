#!/bin/sh
# Build rp-install-<version>.tar.gz from the current checkout.
#
# Output:
#   dist/rp-install-<version>.tar.gz
#   dist/rp-install-<version>.tar.gz.sha256
#   dist/rp-install-latest.tar.gz             (copy of the above)
#   dist/rp-install-latest.tar.gz.sha256
#
# Tarball layout (what the bootstrap wrapper extracts and exec's):
#   scripts/install.sh
#   scripts/install.ps1
#   scripts/lib/*                    (if present)
#   packaging/linux/*
#   packaging/macos/*
#
# Usage:
#   scripts/build-install-tarball.sh [VERSION]
#
# If VERSION is omitted it is derived from server/pyproject.toml.

set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

VERSION=${1:-}
if [ -z "$VERSION" ]; then
    if [ -f "$ROOT/server/pyproject.toml" ]; then
        VERSION=$(grep -E '^version[[:space:]]*=' "$ROOT/server/pyproject.toml" \
            | head -n1 \
            | sed -E 's/.*"([^"]+)".*/\1/')
    fi
fi
if [ -z "${VERSION:-}" ]; then
    echo "ERROR: could not determine version (pass as arg or set in pyproject.toml)" >&2
    exit 1
fi

OUT="$ROOT/dist"
mkdir -p "$OUT"

TARBALL="$OUT/rp-install-${VERSION}.tar.gz"
LATEST="$OUT/rp-install-latest.tar.gz"

# Build file list (only include scripts/lib if it exists).
SET="scripts/install.sh scripts/install.ps1 packaging/linux packaging/macos"
if [ -d "$ROOT/scripts/lib" ]; then
    SET="scripts/install.sh scripts/install.ps1 scripts/lib packaging/linux packaging/macos"
fi

# Sanity-check required entries.
for p in scripts/install.sh scripts/install.ps1 packaging/linux packaging/macos; do
    if [ ! -e "$ROOT/$p" ]; then
        echo "ERROR: missing required path: $p" >&2
        exit 1
    fi
done

# shellcheck disable=SC2086
tar -czf "$TARBALL" -C "$ROOT" $SET

cp "$TARBALL" "$LATEST"

sha256_of() {
    file=$1
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$file" | awk '{print $1}'
    else
        shasum -a 256 "$file" | awk '{print $1}'
    fi
}

SHA=$(sha256_of "$TARBALL")
printf '%s  rp-install-%s.tar.gz\n' "$SHA" "$VERSION" > "$TARBALL.sha256"
printf '%s  rp-install-latest.tar.gz\n' "$SHA" > "$LATEST.sha256"

echo "Built  $TARBALL"
echo "  sha256: $SHA"
echo "Synced $LATEST + sidecar .sha256 files"
