# Remote-Pulse packaging — service units (F1-5)

Cross-OS service unit definitions and idempotent install/uninstall scripts for
the Remote-Pulse agent. Invoked by the top-level bootstrap script
`scripts/install.sh` once the `rp` binary is on PATH.

Tracked by **ADR-0008 §F1 (item: "systemd unit `remote-pulse.service`
instalado por bootstrap")**.

## Tree

```
packaging/
├── linux/
│   ├── remote-pulse.service     # systemd unit (Type=simple, journal logging)
│   ├── install-systemd.sh       # idempotent install + enable --now
│   ├── uninstall-systemd.sh     # stop + disable + rm
│   └── logrotate.conf           # /var/log/rp/*.log daily x7 + reload hook
├── macos/
│   ├── com.monxas.remote-pulse.plist  # LaunchDaemon (RunAtLoad+KeepAlive)
│   ├── install-launchd.sh
│   └── uninstall-launchd.sh
├── windows/
│   ├── install-nssm.ps1         # F7 stub (prints plan)
│   ├── uninstall-nssm.ps1       # F7 stub
│   └── README.md                # F7 TODO detail
└── README.md                    # this file
```

## How `scripts/install.sh` composes this

```sh
# pseudo-código del bootstrap (F1):
case "$(uname -s)" in
    Linux)   sudo packaging/linux/install-systemd.sh ;;
    Darwin)  sudo packaging/macos/install-launchd.sh ;;
    *)       echo "Windows: see packaging/windows/README.md (F7)"; exit 1 ;;
esac
```

The scripts:

- **Detect** the `rp` binary across common install locations
  (uv tool, Homebrew, /usr/local/bin, ~/.local/bin) and patch the unit
  in-place before installing — so packagers don't need a fixed prefix.
- **Create** the canonical data dirs: `/etc/rp`, `/var/lib/rp`, `/var/log/rp`.
- **Enable + start** the service in one step.
- Are **idempotent**: re-running them is safe (re-applies unit, reloads,
  re-bootstraps on macOS after `bootout`).

## Linux specifics

- Unit runs as `root` in F1 (needs `/etc/rp/` + raw network counters).
  F8 will consider a dedicated `rp` user with capabilities.
- Hardening flags applied (F1 baseline): `NoNewPrivileges`, `ProtectSystem=strict`,
  `ProtectHome=read-only`, `PrivateTmp`. Tightened in F8 (see TODO below).
- Logs go to **journald** by default (`journalctl -u remote-pulse -f`).
  `logrotate.conf` only kicks in if the agent also writes file logs to
  `/var/log/rp/*.log` (configurable in agent settings).

## macOS specifics

- Installed as **LaunchDaemon** (system-wide, root) under
  `/Library/LaunchDaemons/`. Not a per-user LaunchAgent.
- Uses `launchctl bootstrap` / `bootout` (modern API; replaces `load`/`unload`).
- Logs go to plain files under `/var/log/rp/` because launchd doesn't have
  journald equivalent.
- On install, if the daemon is already loaded we `bootout` first to make the
  re-install idempotent.

## Windows

Stubs only — see `windows/README.md`. Real implementation is **F7** (PyInstaller
exe + winget manifest + NSSM service).

## Troubleshooting

| Symptom | Linux | macOS |
|---|---|---|
| Service not running | `systemctl status remote-pulse` | `sudo launchctl print system/com.monxas.remote-pulse` |
| Tail logs | `journalctl -u remote-pulse -f` | `tail -f /var/log/rp/stderr.log` |
| Reload after config change | `systemctl restart remote-pulse` | `sudo launchctl kickstart -k system/com.monxas.remote-pulse` |
| `rp` binary not found | Install `rp` first (uv tool install / pipx) then re-run installer | Same — installer probes Homebrew + /usr/local + ~/.local |
| Permission denied on `/etc/rp` | Service runs as root in F1; check umask of files dropped there | Same |

## TODOs deferred to F8 (hardening)

- [ ] **Dedicated `rp` user/group** (Linux) instead of root. Requires
  capability grants (`CAP_NET_RAW` for ICMP, `CAP_NET_ADMIN` if we add
  netlink probes) via `AmbientCapabilities=`.
- [ ] **Stricter systemd sandbox**: `ProtectKernelTunables=yes`,
  `ProtectKernelModules=yes`, `ProtectControlGroups=yes`,
  `RestrictNamespaces=yes`, `RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6`,
  `SystemCallFilter=@system-service`, `LockPersonality=yes`,
  `MemoryDenyWriteExecute=yes`.
- [ ] **macOS sandbox profile** (`sandbox-exec`) or signed + notarized
  binary so Gatekeeper doesn't block on fresh installs.
- [ ] **launchd ProcessType=Background** + `LowPriorityIO` tuning.
- [ ] **Watchdog** (`WatchdogSec=` on Linux) wired to a `rp` self-check
  endpoint — auto-restart if heartbeat loop wedges.
- [ ] **Alpine/musl** unit variant (Open question #5 in ADR-0008).
- [ ] **DR runbook** entry: how to re-install + re-auth after server PBS
  restore (ADR-0008 Apéndice F).

## Manual invocation examples

```sh
# Linux fresh install
sudo packaging/linux/install-systemd.sh
journalctl -u remote-pulse -f

# Linux clean removal
sudo packaging/linux/uninstall-systemd.sh

# macOS fresh install
sudo packaging/macos/install-launchd.sh
sudo launchctl print system/com.monxas.remote-pulse | head -30

# macOS clean removal
sudo packaging/macos/uninstall-launchd.sh
```
