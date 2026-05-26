# Remote-Pulse v1.0.1 — Phase 3 cutover + installer fix + Settings API

Patch release. No breaking changes — agents on v1.0.0 keep working, API version stays at 1.0.0. Existing deployments can upgrade in-place.

## Highlights

- **ADR-0009 Phase 3 — dashboard cutover.** The legacy Jinja+HTMX UI at `/dash/*` is replaced by 302 redirects to the SvelteKit SPA at `/dash-next/*`. Query strings are preserved, all sub-paths (`/dash/hosts`, `/dash/commands`, `/dash/host/{id}`, etc.) map to their SPA equivalents. The one preserved endpoint — `/dash/host/{id}/sparkline-data` — stays verbatim for external consumers; new clients should migrate to `/v1/dash/hosts/{id}/timeseries`.
- **ADR-0009 Phase 4 — Settings API + UI scaffold.** Groups and Users are now editable from the dashboard at `/dash-next/settings/` (admin-only). Seven new endpoints under `/v1/dash/settings/*`. No alembic migration required.
- **Installer fix — `F1 stub` silent skip resolved.** `scripts/install.sh` referenced `$PACKAGING_DIR/install-systemd.sh` instead of the real `packaging/linux/install-systemd.sh`. Every install since `v1.0.0` silently warned `"F1 stub"` and **skipped service registration**, which is why fleet hosts needed manual systemd/launchd setup. Now hard-fails if the unit installer is missing; both systemd and launchd installs are idempotent (`launchctl bootstrap` with legacy fallback on macOS); `--dry-run` flag added for smoke-testing.

## Changes

### Server

- `feat(server-settings)` `/v1/dash/settings/{groups,users}` CRUD with `host_count`/`user_count`, 409 on group-with-hosts delete, self-protection (cannot demote/deactivate/delete the calling admin).
- `feat(web)` `/dash/*` cutover — `dash_redirect` router replaces `web.router` in `main.py`. Legacy `web.py` is unmounted but kept on disk for one-release rollback.
- `chore` `__version__` and `pyproject.toml` bumped to `1.0.1`. `SERVER_API_VERSION` stays at `1.0.0`.

### Dashboard SPA

- `feat(web-settings)` `/settings` page with Groups + Users tabs, dialogs for create/invite, role/group inline editing, toast feedback.
- `feat(web)` API client gained 7 typed Settings functions; 7 TanStack mutation hooks.

### Installer

- `feat(install)` `scripts/install.sh` resolves `packaging/{linux,macos}/install-{systemd,launchd}.sh` correctly; hard-fails on missing installer.
- `feat(install)` `packaging/linux/install-systemd.sh`: systemd preflight, stop-before-overwrite idempotency, `is-active` verification with `journalctl` dump on failure.
- `feat(install)` `packaging/macos/install-launchd.sh`: `launchctl bootstrap` with `launchctl load` legacy fallback, `bootout`-before-overwrite, `chown root:wheel` + `0644`.
- `feat(install)` `scripts/install.ps1`: `-DryRun` switch for symmetry.

### Infra (operator notes, not in release artifacts)

- DNS dual-tailscaled coexistence (rp-server LXC 280): runtime pref `--accept-dns=false` on the secondary `tailscaled-rfrobredo` daemon to stop the resolv.conf fight with the primary. Static `/etc/hosts` entries for the 3 RPi hosts in the secondary tailnet.

## Upgrade

```sh
cd /opt/rp/source
git pull
scripts/build_dashboard.sh
systemctl restart rp-server
```

Agents need no action — version compat unchanged. Fleet hosts that were enrolled by hand can be re-converged onto the canonical systemd/launchd units by re-running `install.sh` (idempotent).

## Caddy

The `@dash_path /dash /dash/*` matcher already proxies to the backend without `forward_auth`, so the cutover works without a Caddyfile change. If your deployment uses a different layout (no `@dash_path` matcher), add `/dash /dash/*` to your public matcher — see `docs/docs/runbooks/rp-dash-phase3-caddy.md`.

## Known follow-ups (deferred to v1.0.2+)

- `web.py` module deletion (kept this release for rollback safety).
- Settings page: row-level ACL beyond `accessible_groups`, audit-trail of settings mutations, magic-link issuance from UI, optimistic mutations.
- `agent_version="main"` reported by all hosts in `/v1/dash/hosts` — agents should report the actual semver (or git sha) instead of the branch name.

## Verifying

```sh
curl -sSI https://rp.monxas.casa/dash/        # expect: 302 to /dash-next/
curl -sSI https://rp.monxas.casa/dash/hosts   # expect: 302 to /dash-next/hosts
curl  -sS https://rp.monxas.casa/health       # expect: {"status":"healthy","version":"1.0.1"}
```

## Acknowledgements

Built end-to-end in a single session via parallel sub-agent orchestration (4 concurrent agents for ADR-0009 Phase 3 cutover, Phase 4 Settings API, installer fix, and DNS dual-tailscaled coexistence). Tests: 27 new (16 settings + 11 redirect), all green.
