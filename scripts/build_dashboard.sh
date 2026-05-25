#!/usr/bin/env sh
# Build the SvelteKit SPA in `web/` and stage it into the FastAPI server's
# static asset tree so the wheel build picks it up. ADR-0009 Phase 0.
#
# Idempotent: deleting + rsyncing means stale assets from previous builds
# never linger in the staged directory. Safe to run repeatedly.
#
# Usage:
#   scripts/build_dashboard.sh
#
# Requirements:
#   - Node 22+ (see web/.nvmrc)
#   - npm
#   - rsync
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WEB_DIR="${ROOT}/web"
TARGET_DIR="${ROOT}/server/src/rp_server/static/dash-next"

if [ ! -d "${WEB_DIR}" ]; then
    echo "ERR ${WEB_DIR} not found — are you running from a remote-pulse checkout?"
    exit 1
fi

if ! command -v node >/dev/null 2>&1; then
    echo "ERR node not on PATH. Install Node 22 (see web/.nvmrc)."
    exit 1
fi

if ! command -v rsync >/dev/null 2>&1; then
    echo "ERR rsync not on PATH."
    exit 1
fi

cd "${WEB_DIR}"

# Use `npm ci` when a lockfile is present (reproducible CI build).
# Fall back to `npm install` for fresh checkouts that haven't generated
# one yet — useful for the very first local build.
if [ -f package-lock.json ]; then
    echo "==> npm ci"
    npm ci --no-audit --no-fund
else
    echo "==> npm install (no lockfile yet)"
    npm install --no-audit --no-fund
fi

echo "==> npm run build"
npm run build

echo "==> staging build → ${TARGET_DIR}"
mkdir -p "${TARGET_DIR}"

# `--delete` keeps the staged tree byte-identical to web/build/ so removed
# hashed assets don't pile up. `--exclude=.gitkeep` preserves the sentinel
# that holds the directory in git for fresh checkouts before the first build.
rsync -a --delete --exclude=.gitkeep "${WEB_DIR}/build/" "${TARGET_DIR}/"

# Re-stamp .gitkeep so a fresh checkout's empty-dir-with-sentinel pattern
# is always present even after `rsync --delete`.
: > "${TARGET_DIR}/.gitkeep"

echo "✓ dashboard staged at ${TARGET_DIR}"
