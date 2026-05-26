# Remote-Pulse v1.0.3 — heartbeat reconciliation + curl-pipe bootstrap

Patch release. No breaking changes. Operator action required to enable the curl-pipe install path: ship the tarball + apply the Caddyfile diff (see below).

## Highlights

- **`Host.agent_version` now reconciles from heartbeats.** Every heartbeat updates the displayed `agent_version` alongside `last_seen_at`. Hosts that drift (in-place upgrade, wrong value at enroll, the v1.0.2 install.sh `main` literal bug) converge automatically on the next heartbeat cycle (~30s). No re-enroll required for the displayed value to catch up.
- **Curl-pipe install works again.** v1.0.1's installer fix required a sibling `packaging/{linux,macos}/` tree, which silently broke the documented `curl URL/install | sh -s -- --token=...` pattern. New `scripts/install-bootstrap.sh` is a POSIX-sh wrapper that: detects a local checkout and execs `install.sh` directly, or downloads `rp-install-<version>.tar.gz` from the configured base URL, verifies SHA256 against a sidecar file, extracts to a tempdir, and execs the real installer. Same flags, same UX.
- **Tarball builder.** `scripts/build-install-tarball.sh <version>` produces `dist/rp-install-<version>.tar.gz` and `dist/rp-install-latest.tar.gz` plus `.sha256` sidecars, ready to drop into `/var/lib/caddy/rp-install/` on the Caddy LXCs.

## Changes

### Server

- `fix(server)` Heartbeat handler now updates `Host.agent_version` in the same SQL statement as `last_seen_at`. Hosts on stale displayed versions converge within one heartbeat cycle.
- `fix(server)` Tz-comparison robustness in `enroll.py`: `enrollment.expires_at` is normalized to tz-aware before comparing to `datetime.now(timezone.utc)` (SQLite-backed test fixture returns naive datetimes even when the row was stored aware; Postgres returns aware).
- `test(server)` New `test_heartbeat_reconciles_agent_version` — enrolls with `agent_version="main"`, heartbeats with `"1.0.3"`, asserts the `Host` row reflects the heartbeat value.
- `chore` `__version__` + `pyproject.toml` → `1.0.3`.

### Install

- `feat(install)` `scripts/install-bootstrap.sh` — curl-pipe wrapper, shellcheck-clean POSIX sh.
- `feat(install)` `scripts/build-install-tarball.sh` — release tarball builder with `.sha256` sidecars.
- `test(install)` `tests/test_install_bootstrap.sh` — 16 asserts cover `--help`, local-checkout fast-path, tarball verification, env overrides.
- `docs(runbook)` `docs/docs/runbooks/rp-install-bootstrap-caddy.md` — Caddyfile diff + scp deploy steps for LXC 270/271.

### Agent

- `chore` `__version__` + `pyproject.toml` → `1.0.3` (lockstep with server).

## Upgrade

```sh
cd /opt/rp/source
git pull
scripts/build_dashboard.sh
systemctl restart rp-server
```

To enable the curl-pipe path on the Caddy LXC fleet:

```sh
# 1. Build tarball (on a host with the repo + Node + Python toolchain)
scripts/build-install-tarball.sh 1.0.3

# 2. Ship to Caddy primary + secondary
scp dist/rp-install-1.0.3.tar.gz dist/rp-install-1.0.3.tar.gz.sha256 \
    dist/rp-install-latest.tar.gz dist/rp-install-latest.tar.gz.sha256 \
    scripts/install-bootstrap.sh \
    root@<caddy>:/var/lib/caddy/rp-install/

# 3. Apply the Caddyfile diff (docs/docs/runbooks/rp-install-bootstrap-caddy.md)
# 4. caddy reload on both LXCs

# Verify
curl -fsSL https://rp.monxas.casa/install | sh -s -- --help
```

## Verifying

```sh
curl -sS https://rp.monxas.casa/health
# {"status":"healthy","version":"1.0.3"}

# After enabling the curl-pipe bootstrap on Caddy:
curl -fsSL https://rp.monxas.casa/install | sh -s -- --show
```

Heartbeat reconciliation is automatic — within ~30s of upgrade, any host's `/v1/dash/hosts` row will reflect its actual running agent version.

## Known follow-ups (deferred to v1.0.4+)

- **Phase 5 polish.** Lighthouse ≥90 audit, axe-core CI gate, Playwright E2E full suite.
- **Phase 4 Settings completion.** Audit trail of settings mutations, magic-link issuance from the UI, row-level ACL beyond `accessible_groups`, optimistic mutations.
- **Fleet re-convergence.** The 8 existing hosts still run hand-rolled `rp-agent.service` units with `uv tool install` binaries at `/root/.local/bin/rp`. The canonical install (PyInstaller + `remote-pulse.service`) is now reachable via the new bootstrap; re-converging is a controlled maintenance task.
- **GH Actions CI workflow.** `release.yml` is still queued from the 2026-05-25 GitHub-side outage. Once status page reports resolved, cancel old runs and (optionally) re-tag to pick up artifact builds.
