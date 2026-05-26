#!/usr/bin/env bash
# tests/test_install_shell.sh — Smoke test for install.sh persistence wiring.
#
# Runs `install.sh --dry-run` and asserts:
#   1. Exit code 0
#   2. Resolved packaging/<os>/install-{systemd|launchd}.sh exists & is executable
#   3. Resolved unit/plist file exists
#   4. Same for re-invocation (idempotency)
#
# Also runs shellcheck on install.sh + companion shell scripts.
#
# Usage:
#   bash tests/test_install_shell.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INSTALL_SH="$REPO_ROOT/scripts/install.sh"
LINUX_DIR="$REPO_ROOT/packaging/linux"
MACOS_DIR="$REPO_ROOT/packaging/macos"

PASS=0
FAIL=0

pass() { printf '  \033[1;32mPASS\033[0m %s\n' "$*"; PASS=$((PASS+1)); }
fail() { printf '  \033[1;31mFAIL\033[0m %s\n' "$*"; FAIL=$((FAIL+1)); }
hdr()  { printf '\n\033[1;34m== %s ==\033[0m\n' "$*"; }

# ---------------------------------------------------------------------------
hdr "1. install.sh exists + is executable"
# ---------------------------------------------------------------------------
[ -x "$INSTALL_SH" ] && pass "scripts/install.sh executable" || fail "scripts/install.sh not executable"

# ---------------------------------------------------------------------------
hdr "2. Packaging directories present"
# ---------------------------------------------------------------------------
[ -x "$LINUX_DIR/install-systemd.sh" ] && pass "packaging/linux/install-systemd.sh executable" || fail "packaging/linux/install-systemd.sh missing or not executable"
[ -f "$LINUX_DIR/remote-pulse.service" ] && pass "packaging/linux/remote-pulse.service exists" || fail "packaging/linux/remote-pulse.service missing"
[ -x "$MACOS_DIR/install-launchd.sh" ] && pass "packaging/macos/install-launchd.sh executable" || fail "packaging/macos/install-launchd.sh missing or not executable"
[ -f "$MACOS_DIR/com.monxas.remote-pulse.plist" ] && pass "packaging/macos/com.monxas.remote-pulse.plist exists" || fail "packaging/macos/com.monxas.remote-pulse.plist missing"

# ---------------------------------------------------------------------------
hdr "3. install.sh --show (dry-plan print)"
# ---------------------------------------------------------------------------
if SHOW_OUT="$(sh "$INSTALL_SH" --show 2>&1)"; then
    if printf '%s' "$SHOW_OUT" | grep -q "systemd or launchd"; then
        pass "--show prints service plan"
    else
        fail "--show output missing service-install mention"
        printf '%s\n' "$SHOW_OUT"
    fi
else
    fail "--show exited non-zero"
fi

# ---------------------------------------------------------------------------
hdr "4. install.sh --dry-run (resolves persistence assets)"
# ---------------------------------------------------------------------------
if DRY_OUT="$(sh "$INSTALL_SH" --dry-run 2>&1)"; then
    pass "--dry-run exit 0"
    case "$(uname -s | tr '[:upper:]' '[:lower:]')" in
        linux)
            printf '%s' "$DRY_OUT" | grep -q "install-systemd.sh" && pass "dry-run mentions install-systemd.sh" || fail "missing install-systemd.sh in output"
            printf '%s' "$DRY_OUT" | grep -q "remote-pulse.service" && pass "dry-run mentions remote-pulse.service" || fail "missing remote-pulse.service in output"
            ;;
        darwin)
            printf '%s' "$DRY_OUT" | grep -q "install-launchd.sh" && pass "dry-run mentions install-launchd.sh" || fail "missing install-launchd.sh in output"
            printf '%s' "$DRY_OUT" | grep -q "com.monxas.remote-pulse.plist" && pass "dry-run mentions plist" || fail "missing plist in output"
            ;;
    esac
    printf '%s' "$DRY_OUT" | grep -q "All persistence assets resolved correctly" && pass "dry-run ok marker present" || fail "missing ok marker"
else
    fail "--dry-run exited non-zero"
    printf '%s\n' "$DRY_OUT"
fi

# ---------------------------------------------------------------------------
hdr "5. install.sh --dry-run idempotency (run twice)"
# ---------------------------------------------------------------------------
sh "$INSTALL_SH" --dry-run >/dev/null 2>&1 && \
sh "$INSTALL_SH" --dry-run >/dev/null 2>&1 && \
    pass "--dry-run is idempotent (two consecutive runs both succeed)" || \
    fail "--dry-run not idempotent"

# ---------------------------------------------------------------------------
hdr "6. Per-packaging-script --dry-run"
# ---------------------------------------------------------------------------
if sh "$LINUX_DIR/install-systemd.sh" --dry-run >/dev/null 2>&1; then
    pass "packaging/linux/install-systemd.sh --dry-run exit 0"
else
    fail "packaging/linux/install-systemd.sh --dry-run failed"
fi
if sh "$MACOS_DIR/install-launchd.sh" --dry-run >/dev/null 2>&1; then
    pass "packaging/macos/install-launchd.sh --dry-run exit 0"
else
    fail "packaging/macos/install-launchd.sh --dry-run failed"
fi

# ---------------------------------------------------------------------------
hdr "7. shellcheck (if installed)"
# ---------------------------------------------------------------------------
if command -v shellcheck >/dev/null 2>&1; then
    SC_FAIL=0
    for f in "$INSTALL_SH" "$LINUX_DIR/install-systemd.sh" "$MACOS_DIR/install-launchd.sh"; do
        if shellcheck -s sh -S warning "$f" 2>&1; then
            pass "shellcheck clean: $f"
        else
            fail "shellcheck warnings: $f"
            SC_FAIL=$((SC_FAIL+1))
        fi
    done
else
    printf '  \033[1;33mSKIP\033[0m shellcheck not installed\n'
fi

# ---------------------------------------------------------------------------
echo ""
printf '======== %d passed, %d failed ========\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
