# Remote-Pulse bootstrap scripts

Ticket **F1-4 (ADR-0008)**. Phase F1 only — Tailscale (F2), SSH keys (F4) and
PyInstaller binaries (F7) are intentionally **not** wired up yet; TODO markers
in the scripts call them out where they will plug in.

## Layout

```
scripts/
├── install.sh          # Bootstrap installer (Linux/macOS, POSIX sh)
├── install.ps1         # Windows stub (full impl in F7)
├── uninstall.sh        # Tear-down (also reachable as `rp uninstall`)
├── lib/
│   ├── detect-os.sh    # detect_os/arch/distro/init_system/pkg_manager
│   ├── install-python.sh  # ensure_python_312 via apt/dnf/brew/apk
│   └── install-uv.sh   # ensure_uv (official installer + version check)
└── README.md           # this file
```

## What `install.sh` does (F1 scope)

1. Parse flags / env (`--token`, `--server`, `--group`, `--hostname`,
   `--version`, `--show`).
2. Detect OS + arch (via `lib/detect-os.sh`).
3. Ensure Python 3.12 (via `lib/install-python.sh`).
4. Ensure `uv` (via `lib/install-uv.sh`).
5. `uv tool install remote-pulse` — from GitHub if reachable, falling back to
   the local dev path `/Users/ramonkamibayashicarrera/monxas-remote-pulse/agent`.
6. `POST $RP_SERVER/v1/enroll` with the enrollment JWT, parse `host_id`.
7. Write `/etc/rp/config.toml` (`root:root` `0600`) + create `/var/lib/rp/`.
8. Hand off to `packaging/install-systemd.sh` or `packaging/install-launchd.sh`
   to register and start the service unit.

### Audit-first usage

```sh
sh install.sh --show
```

Prints the full plan, target server, detected OS/arch, and the SHA256
placeholder. No mutations.

### Silent install

```sh
sh install.sh --token=eyJhbGc... --group=family --server=http://192.168.0.X:8080
```

### Override env-style

```sh
RP_TOKEN=eyJ... RP_GROUP=prod sh install.sh
```

## Uninstall

```sh
sh uninstall.sh --confirm
# or, once the agent CLI is installed:
rp uninstall --confirm
```

Removes service unit, `/etc/rp/`, `/var/lib/rp/`, and the `remote-pulse` uv
tool. Use `--keep-tool` to preserve the binary for re-enrollment.

## Conventions

- **POSIX sh only** — runs under `bash`, `dash`, `ash`, `busybox sh`. No
  `[[`, no arrays, no `local`, no process substitution.
- `set -eu` at the top of every executable script.
- Errors go to stderr with a clear prefix, non-zero exit codes.
- Idempotent: re-running on an already-installed host updates in place.
- `lib/*.sh` files are sourced, never executed; their functions print one
  token to stdout and never call `exit`.

## TODO markers (later phases)

| Phase | Where | What |
|-------|-------|------|
| F2 | `install.sh` step 4 | Server returns Tailscale auth-key; install + join tailnet. |
| F2 | `install.sh` step 4 | Switch default `RP_SERVER` to `https://rp.monxas.casa`. |
| F4 | `install.sh` post-enroll | Generate ed25519 keypair; push pubkey to server. |
| F4 | `uninstall.sh` | Call `/v1/keys/revoke` before deleting `/var/lib/rp`. |
| F7 | `install.sh` step 3 | Replace `uv tool install` with PyInstaller binary download + SHA256 verify against `$RP_SERVER/install.sha256`. |
| F7 | `install.ps1` | Implement real Windows install (winget + PyInstaller `.exe`). |
| F7 | build pipeline | Inject SHA256 of the published `install.sh` into header comment. |
