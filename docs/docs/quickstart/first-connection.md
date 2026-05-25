# First connection — from zero to dashboard

This walkthrough takes you from "I just heard about Remote-Pulse" to
"my host is sending heartbeats and I can see it in the dashboard" in under
five minutes.

## Prerequisites

- A host with internet access (Linux/macOS/Windows).
- An **enrollment token** issued by a Remote-Pulse server admin.
- (Optional) A Tailscale account if the host is not yet on a tailnet — the
  installer handles this automatically using the token-issued ephemeral
  auth-key.

## Step 1 — Get an enrollment token

There are three ways to receive a token:

=== "Telegram magic link"

    The server admin sends you a one-tap Telegram message with a link such as
    `https://rp.monxas.casa/install?token=eyJhbGc...`. Tap it on the target
    host and follow the install prompt.

=== "Web magic link (OIDC)"

    Open `https://rp.monxas.casa/enroll` in a browser, log in via PocketID,
    and the page renders a personalised install command with the token
    pre-embedded. Copy-paste it into the host's terminal.

=== "Admin CLI"

    If you are the admin:

    ```bash
    rp admin enroll --group=family --ttl=24h --max-uses=1
    ```

    The CLI prints a JWT plus the full one-liner command to share.

The token is **single-use** and **expires in 24 hours**. It binds to the
host's machine fingerprint on first use, so you cannot reuse it elsewhere
even if leaked afterwards.

## Step 2 — Run the install command

Linux/macOS:

```bash
curl -fsSL https://rp.monxas.casa/install | sh -s -- --token=<token>
```

Windows:

```powershell
winget install Monxas.RemotePulse
rp install --token=<token>
```

You will see a sequence of progress lines:

```text
==> Detecting OS/arch...                       linux/x64
==> Installing Tailscale...                    ok (v1.78.1)
==> Downloading rp binary...                   ok
==> Verifying SHA256...                        ok
==> Enrolling with server...                   ok (host_id=550e8400-...)
==> Joining tailnet...                         ok (100.86.42.7)
==> Generating SSH key...                      ok (ed25519, SHA256:W+7...)
==> Installing systemd service...              ok
==> Starting agent...                          ok (heartbeat in 3s)

✓ Remote-Pulse installed. Host 'my-laptop' registered to group 'family'.
  Dashboard: https://dash.rp.monxas.casa
  Local CLI: rp status
```

## Step 3 — Verify in the dashboard

Open the dashboard on any device:

- **TUI:** `rp dash` on a workstation with Tailscale access.
- **Web:** `https://dash.rp.monxas.casa` — log in via PocketID passkey.

Within ~30 seconds your host appears with green status (last heartbeat
under 60 s) and live sparklines for CPU, memory, disk and network.

## Common pitfalls

| Symptom | Cause | Fix |
|---------|-------|-----|
| `curl: (22) The requested URL returned error: 401` | Token expired or already used | Ask the admin to issue a new one |
| `tailscale: command not found` after install | Tailscale install failed silently (rare) | Install manually: `curl -fsSL https://tailscale.com/install.sh \| sh` then re-run `rp install` |
| Host appears in dashboard but `last_seen` keeps growing | Agent service not enabled at boot | `sudo systemctl enable --now remote-pulse` (Linux) |
| `rp dash` hangs at "Connecting to server" | Workstation not on the tailnet | `tailscale up` first |
| Windows: SmartScreen blocks the binary | PyInstaller binary not yet signed with reputation | Use `winget install` instead, or see [Windows Defender troubleshooting](../troubleshooting/windows-defender.md) |

## What's next

- Learn the [`rp` CLI surface](../guide/cli.md).
- If this is a `prod` or `iarq` host, review
  [local-approval enforcement](../guide/local-approval.md) — destructive
  remote commands are denied by default until you flip explicit flags.
- Read the [security model](../architecture/security.md) to understand the
  three-layer auth chain.
