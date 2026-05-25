# Install on Linux and macOS

There are three supported install paths on Unix-like systems. Pick one.

## Path A — One-line curl-pipe-sh (default)

```bash
curl -fsSL https://rp.monxas.casa/install | sh -s -- \
  --token=<your-enrollment-token> \
  --group=family \
  --hostname=$(hostname -s)
```

The script:

1. Detects OS and architecture.
2. Installs Tailscale if missing (via the official upstream installer).
3. Downloads the `rp` binary from GitHub Releases and verifies its SHA256.
4. Calls `POST /v1/enroll` with the JWT to get an ephemeral Tailscale auth key.
5. Joins the tailnet (`tailscale up --ssh`).
6. Generates an ed25519 SSH key and registers the pubkey.
7. Installs a systemd unit (Linux) or launchd plist (macOS) and starts it.

### Audit-first mode

`curl-pipe-sh` is a frequent source of "I don't trust this" — fair. Use the
audit-first variant:

```bash
curl -fsSL https://rp.monxas.casa/install -o /tmp/rp-install.sh
sha256sum /tmp/rp-install.sh
# Compare against the published anchor at:
#   https://rp.monxas.casa/install.sha256
less /tmp/rp-install.sh
sh /tmp/rp-install.sh --token=<your-enrollment-token>
```

The server also serves the script through a `--show` query parameter so you can
dump it to stdout without saving:

```bash
curl -fsSL 'https://rp.monxas.casa/install?show=1' | less
```

## Path B — `pipx install` (Python power-users)

If you already have Python 3.12+ and `pipx`:

```bash
pipx install remote-pulse
rp install --token=<your-enrollment-token>
```

This is the recommended path on Alpine Linux and on hosts where you want
`pipx upgrade` to handle agent rollovers.

!!! note
    `pipx install` does **not** install Tailscale. Install it separately
    before running `rp install`:

    ```bash
    curl -fsSL https://tailscale.com/install.sh | sh
    ```

## Path C — Manual binary download

For users that want full control over the download URL and verification:

```bash
# Linux x86_64 example
ARCH=$(uname -m); [ "$ARCH" = "x86_64" ] && ARCH=x64
curl -fsSL -o rp "https://github.com/monxas/remote-pulse/releases/latest/download/rp-linux-${ARCH}"
curl -fsSL -o rp.sha256 "https://github.com/monxas/remote-pulse/releases/latest/download/rp-linux-${ARCH}.sha256"
sha256sum -c rp.sha256
sudo install -m 0755 rp /usr/local/bin/rp
rp install --token=<your-enrollment-token>
```

## Post-install verification

```bash
rp status       # local agent state + last heartbeat timestamp
rp version      # binary version + API compat range
rp dash         # launch the TUI dashboard
```

You should see the host appear in `rp dash` within a few seconds.

## Uninstall

```bash
sudo rp uninstall --confirm
```

This stops and removes the service, revokes the host's SSH key on the server,
and deletes the local config under `/etc/rp/`.

## Next steps

- [First connection walkthrough](first-connection.md)
- [`rp` CLI reference](../guide/cli.md)
- [Local-approval enforcement](../guide/local-approval.md) — required reading
  for `prod`/`iarq` group hosts.
