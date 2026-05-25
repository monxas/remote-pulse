#!/usr/bin/env sh
# Renders winget manifests with version + SHA256 substituted.
# Usage: ./render-manifests.sh <version> <installer_url> <sha256_hex> <output_dir>
#
# Reads *.yaml files from the script directory, replaces placeholders
# ({VERSION}, {INSTALLER_URL}, {SHA256}), and writes results to <output_dir>.
#
# Used by .github/workflows/release.yml (submit-winget job) and for local
# manual submission per agent/packaging/winget/README.md.
set -eu

if [ "$#" -ne 4 ]; then
    echo "Usage: $0 <version> <installer_url> <sha256_hex> <output_dir>" >&2
    exit 2
fi

VERSION="$1"
URL="$2"
SHA="$3"
OUT="$4"

# Lowercase SHA per winget-pkgs convention.
SHA_LC=$(printf '%s' "$SHA" | tr '[:upper:]' '[:lower:]')

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

mkdir -p "$OUT"

for src in "$SCRIPT_DIR"/Monxas.RemotePulse*.yaml; do
    name=$(basename "$src")
    sed -e "s|{VERSION}|$VERSION|g" \
        -e "s|{INSTALLER_URL}|$URL|g" \
        -e "s|{SHA256}|$SHA_LC|g" \
        "$src" > "$OUT/$name"
done

echo "Rendered manifests to $OUT:"
ls -1 "$OUT"
