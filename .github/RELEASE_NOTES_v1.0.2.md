# Remote-Pulse v1.0.2 — agent_version bug + Phase 3 cleanup

Patch release. No breaking changes. Existing agents on v1.0.0/v1.0.1 keep working.

## Highlights

- **`agent_version="main"` bug fixed.** Root cause: `scripts/install.sh` sent the literal value of `${RP_VERSION:-main}` (a git ref) as the `agent_version` field in the `/v1/enroll` payload. Every host installed since v1.0.0 reported its branch name instead of a semver. Fix: after `uv tool install`, the installer now parses `rp --version` and uses the resolved semver. Heartbeat path was already correct (reads `__version__`).
- **Phase 3 legacy cleanup.** `server/src/rp_server/routers/web.py` and its 3 Jinja templates (240 LOC total) are now deleted. They were kept on disk for one-release rollback grace after v1.0.1's Phase 3 cutover. `jinja2` stays as a dependency because `enrollment_links` still uses it for the `/enroll-link/*` admin HTML surfaces.

## Changes

### Agent

- `fix(agent-install)` `scripts/install.sh` and `scripts/install.ps1` now resolve the actual installed agent version by parsing `rp --version` output and use that for the enroll payload (instead of the `--version` flag's git ref).
- `chore` `__version__` and `pyproject.toml` bumped to `1.0.2` (agent + server in sync).
- `test(agent)` New `agent/tests/test_version.py` (5 tests) locks `__init__.py` ↔ `pyproject.toml`, asserts semver, blocks git-ref values from being reported.

### Server

- `chore(server)` Deleted `routers/web.py` and `templates/{dashboard,partials/host_row,partials/hosts_table_body}.html`. 71 routes still registered, app imports clean.
- No API surface change. `SERVER_API_VERSION` stays at `1.0.0`.

## Upgrade

```sh
cd /opt/rp/source
git pull
scripts/build_dashboard.sh
systemctl restart rp-server
```

Fleet agents need no action for compatibility. To pick up the `agent_version` fix on existing hosts, either:
- **Re-enroll** (run install.sh again with a fresh token) — the new install.sh will report the correct semver.
- **Wait for v1.0.3**, which will land server-side reconciliation of `Host.agent_version` from heartbeat data.

For visual cleanup right now, the operator may run a one-off SQL update on the prod DB:

```sql
UPDATE hosts SET agent_version = '1.0.0' WHERE agent_version = 'main';
```

(All 8 existing hosts run v1.0.0 agent code; the literal `main` is the misreport.)

## Verifying

```sh
curl -sS https://rp.monxas.casa/health   # expect: {"status":"healthy","version":"1.0.2"}
```

After re-enrollment of any host, the `/v1/dash/hosts` response will show `agent_version: "1.0.2"` (or whatever semver is actually installed).

## Known follow-ups (deferred to v1.0.3+)

- **Server-side `Host.agent_version` reconciliation from heartbeats.** The heartbeat router updates `heartbeats` + `agent_versions` tables, but not `Host.agent_version` which is what `/v1/dash/hosts` reads. Until that's wired up, the displayed value is whatever was POSTed at enroll time.
- **Curl-pipe install bootstrap.** The new `install.sh` requires a sibling `packaging/{linux,macos}/` tree, which breaks the `curl URL | sh` single-file pattern. A small bootstrap script that fetches a tarball is needed before `/var/lib/caddy/rp-install/install.sh` can be updated to the canonical version. Until then, new hosts must clone the repo and run `scripts/install.sh` directly.
- **Fleet re-convergence.** The 8 existing hosts use hand-rolled `rp-agent.service` units with `uv tool install` binaries at `/root/.local/bin/rp`; the new canonical installer (PyInstaller binaries + `remote-pulse.service`) targets a different layout. Re-convergence requires a controlled maintenance window — deferred.

## Acknowledgements

Built end-to-end via parallel sub-agent orchestration (3 concurrent agents for agent_version fix, web.py cleanup, GH Actions diagnostic). The GH Actions diagnostic agent identified a concurrent GitHub-side outage that prevented v1.0.1 binary artifacts from being built — manual `gh release create` was used as workaround.
