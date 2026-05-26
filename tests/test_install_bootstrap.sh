#!/usr/bin/env bash
# tests/test_install_bootstrap.sh — Smoke test for install-bootstrap.sh
# and build-install-tarball.sh.
#
# Asserts:
#   1. install-bootstrap.sh --help exits 0 and prints usage
#   2. From a local checkout, install-bootstrap.sh exec's into install.sh
#      (validated by passing --help so the inner installer also exits 0
#      cleanly without performing any network / mutation steps)
#   3. build-install-tarball.sh produces dist/rp-install-<version>.tar.gz
#      with the expected layout and a matching .sha256 sidecar
#   4. shellcheck passes on both new scripts (when shellcheck is available)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BOOTSTRAP="$REPO_ROOT/scripts/install-bootstrap.sh"
BUILDER="$REPO_ROOT/scripts/build-install-tarball.sh"

PASS=0
FAIL=0

pass() { printf '  \033[1;32mPASS\033[0m %s\n' "$*"; PASS=$((PASS+1)); }
fail() { printf '  \033[1;31mFAIL\033[0m %s\n' "$*"; FAIL=$((FAIL+1)); }
hdr()  { printf '\n\033[1;34m== %s ==\033[0m\n' "$*"; }

# ---------------------------------------------------------------------------
hdr "1. install-bootstrap.sh exists + is executable"
# ---------------------------------------------------------------------------
[ -x "$BOOTSTRAP" ] && pass "install-bootstrap.sh executable" || fail "install-bootstrap.sh not executable"
[ -x "$BUILDER" ]   && pass "build-install-tarball.sh executable" || fail "build-install-tarball.sh not executable"

# ---------------------------------------------------------------------------
hdr "2. --help exits 0 and prints usage"
# ---------------------------------------------------------------------------
HELP_OUT="$("$BOOTSTRAP" --help 2>&1)"
if printf '%s' "$HELP_OUT" | grep -q "install-bootstrap"; then
    pass "--help mentions install-bootstrap"
else
    fail "--help output missing 'install-bootstrap': $HELP_OUT"
fi

# ---------------------------------------------------------------------------
hdr "3. Local checkout fast-path exec's into install.sh"
# ---------------------------------------------------------------------------
# Invoking with --help should be forwarded to install.sh (via exec) and that
# script also exits 0 with its own help text.
LOCAL_OUT="$("$BOOTSTRAP" --help 2>&1 || true)"
# bootstrap prints help and exits BEFORE attempting fast-path, so to test
# the fast-path we use --dry-run + --show via env var indirection. Simpler:
# verify that without flags requiring network, the script either errors
# clearly (no token) or hands off to install.sh. install.sh requires
# --token unless --show. Use --show to validate fast-path end-to-end.
if SHOW_OUT="$("$BOOTSTRAP" --show 2>&1)"; then
    if printf '%s' "$SHOW_OUT" | grep -q "Remote-Pulse installer plan"; then
        pass "--show forwarded into install.sh (fast-path works)"
    else
        fail "--show ran but install.sh plan banner missing"
        printf '%s\n' "$SHOW_OUT"
    fi
else
    fail "--show via bootstrap failed; output:"
    printf '%s\n' "$SHOW_OUT"
fi

# ---------------------------------------------------------------------------
hdr "4. build-install-tarball.sh produces expected artefact"
# ---------------------------------------------------------------------------
WORK_DIST="$REPO_ROOT/dist"
rm -rf "$WORK_DIST"
if BUILD_OUT="$("$BUILDER" 9.9.9-test 2>&1)"; then
    pass "build script exited 0"
else
    fail "build script exited non-zero: $BUILD_OUT"
fi

TARBALL="$WORK_DIST/rp-install-9.9.9-test.tar.gz"
SHAFILE="$TARBALL.sha256"
LATEST="$WORK_DIST/rp-install-latest.tar.gz"

[ -f "$TARBALL" ] && pass "tarball $TARBALL exists" || fail "tarball missing"
[ -f "$SHAFILE" ] && pass "sha256 sidecar exists" || fail "sha256 sidecar missing"
[ -f "$LATEST" ]  && pass "latest tarball copy exists" || fail "latest copy missing"

# Verify content
if tar -tzf "$TARBALL" >/dev/null 2>&1; then
    pass "tarball is a valid gzip+tar"
else
    fail "tarball is corrupt"
fi
TLIST="$(tar -tzf "$TARBALL")"
for entry in "scripts/install.sh" "scripts/install.ps1" "packaging/linux/install-systemd.sh" "packaging/macos/install-launchd.sh"; do
    if printf '%s\n' "$TLIST" | grep -q "^$entry$"; then
        pass "tarball contains $entry"
    else
        fail "tarball missing $entry"
    fi
done

# Verify SHA256 sidecar matches actual tarball.
if command -v sha256sum >/dev/null 2>&1; then
    ACTUAL_SHA="$(sha256sum "$TARBALL" | awk '{print $1}')"
else
    ACTUAL_SHA="$(shasum -a 256 "$TARBALL" | awk '{print $1}')"
fi
SIDECAR_SHA="$(awk '{print $1}' "$SHAFILE")"
if [ "$ACTUAL_SHA" = "$SIDECAR_SHA" ]; then
    pass "sha256 sidecar matches tarball ($ACTUAL_SHA)"
else
    fail "sha256 mismatch: actual=$ACTUAL_SHA sidecar=$SIDECAR_SHA"
fi

# Cleanup
rm -rf "$WORK_DIST"

# ---------------------------------------------------------------------------
hdr "5. shellcheck (best-effort)"
# ---------------------------------------------------------------------------
if command -v shellcheck >/dev/null 2>&1; then
    if shellcheck -s sh "$BOOTSTRAP"; then
        pass "shellcheck install-bootstrap.sh"
    else
        fail "shellcheck install-bootstrap.sh"
    fi
    if shellcheck -s sh "$BUILDER"; then
        pass "shellcheck build-install-tarball.sh"
    else
        fail "shellcheck build-install-tarball.sh"
    fi
else
    printf '  \033[1;33mSKIP\033[0m shellcheck not installed\n'
fi

# ---------------------------------------------------------------------------
printf '\n\033[1;34m== Summary ==\033[0m\n'
printf '  passed: %d\n' "$PASS"
printf '  failed: %d\n' "$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
