# `rp` CLI reference

The `rp` binary is both the **agent service** and the **operator CLI**. All
sub-commands share the same `rp` entrypoint.

```text
rp [GLOBAL OPTIONS] COMMAND [ARGS]...

Global options:
  --version          Print version and exit
  --help             Show help and exit
```

## Lifecycle commands

### `rp install` <span class="rp-badge shipped">F1</span>

Bootstrap a host: enroll, join the tailnet, generate the SSH key, install the
service.

| Flag | Default | Description |
|------|---------|-------------|
| `--token <jwt>` | *(required)* | Enrollment JWT issued by `rp admin enroll`. |
| `--server <url>` | `https://rp.monxas.casa` | Server URL for enrollment. |
| `--hostname <name>` | auto-detect | Override the reported hostname. |
| `--group <name>` | `default` | Group to register under (`prod`, `family`, `iarq`, ...). |
| `--config-path <path>` | OS-default | Override config file location. |

```bash
sudo rp install --token=eyJhbGc... --group=prod
```

### `rp register` <span class="rp-badge shipped">F1</span>

Re-register an existing install with the server (used when the host
fingerprint or hostname changes).

### `rp heartbeat` <span class="rp-badge shipped">F1</span>

Send one heartbeat or run the heartbeat loop.

| Flag | Description |
|------|-------------|
| `--once` | Send a single heartbeat and exit. |
| `--daemon` | Run continuously (used by the systemd unit). |
| `--config-path <path>` | Override config location. |

### `rp status` <span class="rp-badge shipped">F1</span>

Print local agent state, configuration paths and last heartbeat timestamp.

```bash
rp status
```

### `rp version` <span class="rp-badge shipped">F1</span>

Print the binary version, build commit and API compatibility range.

### `rp uninstall` <span class="rp-badge shipped">F1</span>

Stop the service, revoke the host SSH key on the server, delete `/etc/rp/`.

| Flag | Description |
|------|-------------|
| `--confirm` | Skip the interactive confirmation prompt. |

## Dashboard

### `rp dash` <span class="rp-badge shipped">F3</span>

Launch the TUI dashboard (Textual + textual-plotext).

| Flag | Description |
|------|-------------|
| `--server <url>` | Override the server URL for this session. |

| Keybinding | Action |
|------------|--------|
| `↑` / `↓` | Move host selection |
| `Enter` | Open detail pane for selected host |
| `Tab` / `Shift+Tab` | Cycle focus across the 3 panes |
| `r` | Force refresh now |
| `/` | Filter hosts by name |
| `q` | Quit |
| `?` | Show help overlay |

See the [TUI dashboard guide](tui-dashboard.md) for layout details.

## SSH key lifecycle <span class="rp-badge shipped">F4</span>

### `rp keys init`

Generate an ed25519 keypair under `/etc/rp/host_key` and register the pubkey
with the server. Idempotent.

```bash
sudo rp keys init
```

### `rp keys status`

Print local key fingerprint plus server-side registration state.

### `rp keys sync`

Pull the authoritative `authorized_keys` for this host from the server and
write atomically to `/etc/rp/authorized_keys.d/managed`. Idempotent (only
writes if SHA256 differs).

```bash
sudo rp keys sync
```

### `rp keys rotate`

Generate a new key, register it, revoke the old one, sync `authorized_keys`.

| Flag | Description |
|------|-------------|
| `--reason <text>` | *(required)* Audit-log reason. |

```bash
sudo rp keys rotate --reason="scheduled rotation 2026Q2"
```

### `rp keys configure-sshd`

Edit `/etc/ssh/sshd_config` to add `/etc/rp/authorized_keys.d/managed` to
`AuthorizedKeysFile`. Keeps a backup at `sshd_config.rp-backup` and reloads
sshd.

## Local-approval enforcement <span class="rp-badge shipped">F4</span>

These flip flag files under `/etc/rp/` that the agent consults **before**
executing server-issued commands. See the
[local-approval guide](local-approval.md) for the full decision model.

### `rp local status`

Print current local-policy state (which flags are set, TTLs, whitelists).

### `rp local allow-exec`

```bash
sudo rp local allow-exec --ttl=24h
```

Touch `/etc/rp/allow-remote-exec`. Required for `exec_shell` on
`prod`/`iarq` group hosts.

### `rp local deny-exec`

Remove the flag immediately (revoke remote exec capability).

### `rp local approve-write`

```bash
sudo rp local approve-write --ttl=5m
```

Time-limited approval for `file_write` operations.

### `rp local whitelist-add` / `whitelist-rm` / `whitelist-show`

Manage per-type allowlists.

```bash
sudo rp local whitelist-add restart nginx.service
sudo rp local whitelist-add read /var/log/syslog
sudo rp local whitelist-show restart
sudo rp local whitelist-rm restart nginx.service
```

### `rp local evaluate`

Simulate a server command against the current local policy without executing
it. Useful for debugging "why is my command rejected?".

```bash
sudo rp local evaluate exec_shell \
  --payload='{"cmd":"systemctl restart nginx"}' \
  --group=prod
# → ALLOW  (allow-remote-exec set, restart-whitelist matches)
```

## Remote control <span class="rp-badge planned">F4 / F6</span>

### `rp ssh <host>` <span class="rp-badge planned">F6</span>

Wrapper that resolves the host via Tailscale MagicDNS and prefers
`tailscale ssh`, falling back to classic `ssh` with the managed key.

### `rp screen <host>` <span class="rp-badge planned">F6</span>

Open RustDesk (Direct IP) or Sunshine against the target.

| Flag | Description |
|------|-------------|
| `--protocol={rustdesk,sunshine,vnc}` | Force a specific protocol. |

### `rp exec <host|group> -- <cmd>` <span class="rp-badge planned">F4</span>

Run a shell command remotely with audit logging.

## Admin <span class="rp-badge planned">F5+</span>

The `rp admin` namespace is reserved for server-side operations (enrollment,
upgrades, multi-user invitations). It is documented separately once F5 lands;
see the [ADR-0008 Appendix C](https://docs.monxas.casa/architecture/adr/ADR-0008-remote-pulse/)
for the planned surface.

Preview:

```bash
rp admin enroll --group=family --ttl=24h --max-uses=1
rp admin hosts
rp admin commands --host=pmx-50 --since=1h
rp admin upgrade prod --canary=1
rp admin invite hermano@example.com --group=family
rp admin reauth pmx-50
rp admin compat
rp admin clock-skew
```
