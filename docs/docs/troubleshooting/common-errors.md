# Common errors

This page collects the error messages most likely to surface during install
or daily use, with their root cause and the fix.

## Install-time

### `curl: (22) The requested URL returned error: 401`

**Cause:** the enrollment token is expired, already used, or invalid.

**Fix:** ask the admin to issue a new one with `rp admin enroll`.

### `tailscale: command not found`

**Cause:** Tailscale install step failed silently (intermittent network).

**Fix:** install manually then re-run `rp install`:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
```

### `SHA256 mismatch when verifying rp binary`

**Cause:** download was corrupted, or the GitHub Release was updated between
your download and the SHA256 anchor refresh.

**Fix:** re-download both files in the same minute. If the mismatch persists,
verify against the cosign signature instead (post-F8):

```bash
cosign verify-blob --signature rp.sig --certificate rp.pem rp
```

### `Error: token bound to a different machine fingerprint`

**Cause:** the JWT was already consumed by another host, and binding now
rejects the second attempt.

**Fix:** request a new token.

## Runtime

### Host appears in dashboard but `last_seen` keeps growing

**Cause:** the agent service is not running.

**Fix:**

```bash
sudo systemctl status remote-pulse      # Linux
sudo launchctl print system/com.monxas.remote-pulse  # macOS
Get-Service RemotePulse                 # Windows
```

If stopped:

```bash
sudo systemctl enable --now remote-pulse
```

### `rp dash` hangs at "Connecting to server"

**Cause:** the workstation is not on the tailnet.

**Fix:**

```bash
tailscale up
rp dash
```

### Server command rejected with `local_policy_deny`

**Cause:** a `/etc/rp/` flag required for the command is missing.

**Fix:** see [local-approval enforcement](../guide/local-approval.md). On the
target host:

```bash
sudo rp local status
sudo rp local evaluate <cmd_type> --payload='...' --group=<group>
```

Then flip the missing flag with `rp local allow-exec` /
`rp local approve-write` as appropriate.

### Server command rejected with `signature_invalid`

**Cause:** server signing key rotation in progress, or a clock issue with
the command's `iat` claim.

**Fix:** check `journalctl -u remote-pulse | grep sig`. If rotation is in
progress, wait for `POST /v1/agent/rotate-trust` to land. If clock,
`timedatectl status`.

### `version_skew` in CLI banner

**Cause:** agent or server is outside the N-2 deprecation window.

**Fix:** upgrade. See [API compatibility](../architecture/api-compat.md).

### `Postgres connection pool exhausted`

**Cause:** spike in agent reconnects after server restart.

**Fix:** the server applies rate-limit drain (100 items/s); wait 1-2 min.
Persistent issue → tune `db_connection_pool_size` in server config.

## See also

- [Windows Defender false positives](windows-defender.md)
- [Operations troubleshooting](../ops/troubleshooting.md)
