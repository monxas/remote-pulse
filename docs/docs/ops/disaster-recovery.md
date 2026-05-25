# Disaster recovery

This runbook covers the worst-case scenarios for the Remote-Pulse server
(LXC 280) and the signing-key compromise case. It is exercised at least
once per quarter as a drill.

Source of truth: [ADR-0008 Appendix F](https://docs.monxas.casa/architecture/adr/ADR-0008-remote-pulse/).

## Case F1 — Total loss of LXC 280

The server LXC is unreachable: filesystem corruption, host hardware
failure, datacenter accident.

### Detection

- Telegram alert `host_down: rp-server` triggered by Healthchecks ping
  miss.
- Grafana `Remote-Pulse Fleet` panel red.
- Confirm with `pct status 280` on `pmx-50` (and `pmx-51`).

### Recovery options, in order of preference

#### R1 — Restore from PBS snapshot (RTO < 10 min)

```bash
# On pmx-50 (or pmx-51 if pmx-50 lost):
pct restore 280 /var/lib/pbs/backups/lxc-280-<latest>.tar.zst \
  --storage local-zfs --force
pct start 280
pct exec 280 -- tailscale up    # rejoin tailnet
pct exec 280 -- systemctl status rp-server
```

If ZFS replication to `pmx-51` is configured, prefer the replicated dataset:

```bash
zfs rollback rpool/data/subvol-280-disk-0@latest
```

#### R2 — Ansible provision + pg_dump restore (RTO ~ 30 min)

If PBS snapshot is unavailable but the nightly `pg_dump` on the NAS is:

```bash
# 1. Provision a fresh LXC 280 from Ansible
cd ~/homelab-infra
ansible-playbook -i inventory playbooks/remote-pulse-server.yml \
  --limit pmx-50 --tags lxc,postgres

# 2. Restore Postgres
pct exec 280 -- pg_restore -d rp_server \
  /mnt/nas/backups/rp-server/pg_dump-<latest>.sql.gz --clean --if-exists

# 3. Verify tables
pct exec 280 -- psql rp_server -c '\dt'

# 4. Rejoin tailnet
pct exec 280 -- tailscale up --hostname=rp-server \
  --advertise-tags=tag:rp-server --authkey=<admin-one-time>

# 5. Start FastAPI
pct exec 280 -- systemctl start rp-server
```

#### R3 — Rebuild from scratch (RTO ~ 2 h, last resort)

Required only if both PBS and `pg_dump` are gone. Means re-enrolling the
fleet manually.

### Post-restore checklist

Regardless of which path:

1. **Re-issue Tailscale auth-keys.** Old ephemeral keys may still be valid
   on the Tailscale side but are not needed; clean them via the Tailscale
   admin console. Issue a fresh pool of 10 reusable enrollment keys.
2. **Fleet re-auth.** Agents that have been disconnected for more than
   15 minutes call:
   ```http
   POST /v1/agent/reauth
   { "host_id": "...",
     "last_known_server_pubkey": "...",
     "machine_fingerprint": "..." }
   ```
   The server validates against the restored Postgres and issues a new
   session token without requiring full re-enrollment.
3. **Verify** with:
   ```bash
   rp admin hosts
   ```
   All hosts should show a `last_seen` within the heartbeat cadence.
4. **Telegram broadcast.** Notify family and clients that service is back
   if the outage was visible to them.

### What's preserved during R3

- Each host keeps `/etc/rp/authorized_keys.d/managed`, so **SSH works in
  degraded mode** even while the server is rebuilt.
- The agents continue collecting metrics and buffering them locally (up to
  100 MB / 24 h FIFO).
- Audit-log records waiting to be acked are kept indefinitely on the
  agent side — they are never discarded.

### What's lost during R3

- Audit-log history older than the last backup.
- Sparkline raw history (30 d) if the backup is older than 30 d.
- Continuous-aggregate (5 min, 1 y) data outside the backup window.

## Case F2 — Compromise of Ed25519 signing key

The server-side signing key is suspected compromised — for instance,
forensics shows anomalous `rejected_reason=signature_invalid` spikes in
Loki, or an IR investigation surfaces a leaked private key.

1. **Immediate rotation:**
   ```bash
   rp admin rotate-signing-key
   ```
   Generates a new keypair on LXC 280 and produces a `rotation-envelope`
   signed by the **old** key.
2. **Mark all sessions `requires_reauth`** in Postgres (the rotation
   command does this automatically).
3. **Push the new public key to agents:**
   ```http
   POST /v1/agent/rotate-trust
   { "new_pubkey": "...",
     "envelope_signed_by_old": "..." }
   ```
   Agents verify the envelope chain and pin the new key. Optionally they
   wait for a Telegram confirm if `/etc/rp/require-rotation-confirm`
   exists.
4. **Re-issue pending commands** under the new key. The old key's queue is
   dropped.
5. **Audit log** records `signing_key_rotated` with timestamps.

## DR drill

### Cadence

- **Quarterly minimum.** Bump to semestral only after 6 months without
  incidents.

### Procedure

1. In a fresh temporary LXC (id 283), restore the latest `pg_dump` from
   NAS.
2. Run `rp admin verify-restore`. Expected output: list of hosts, last-seen
   timestamps, audit log row count.
3. Spin up a disposable test agent in a container, run
   `rp install --token=<drill-token>` against the temp server, confirm it
   appears in `rp admin hosts`.
4. Destroy LXC 283 and the test agent.
5. Document the real RTO observed in `docs/runbooks/dr-drill-log.md`
   (private repo).

### Drill exit criteria

- Restore completes within RTO target (≤30 min).
- Agent re-auth succeeds via `/v1/agent/reauth` without full
  re-enrollment.
- Audit log integrity verified (`SELECT count(*) FROM commands`).

## RTO / RPO targets

| Scenario | RTO target | RPO target |
|----------|------------|------------|
| LXC 280 lost, PBS snapshot available | 10 min | 24 h (last PBS snapshot) |
| LXC 280 lost, only pg_dump available | 30 min | 24 h (nightly dump) |
| LXC 280 lost, no backups | 2 h | indefinite (rebuild from agents) |
| Signing key compromise | 15 min | n/a |

## See also

- [Backup strategy](backups.md)
- [Security model — signing key rotation](../architecture/security.md#rotation-procedure)
- [ADR-0008 Appendix F](https://docs.monxas.casa/architecture/adr/ADR-0008-remote-pulse/) — original DR spec
