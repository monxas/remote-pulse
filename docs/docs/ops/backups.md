# Backup strategy

Remote-Pulse backups serve two needs: **DR for the server LXC** and
**audit-log retention** for forensic purposes.

## What gets backed up

| Source | Destination | Cadence | Retention |
|--------|-------------|---------|-----------|
| LXC 280 root + data (whole CT) | Proxmox Backup Server (PBS) | nightly + on-demand | 14 daily + 4 weekly + 6 monthly |
| Postgres `rp_server` (`pg_dump`) | NAS (BTRFS) | nightly 03:30 | 30 days |
| Postgres WAL archive | NAS | continuous | 7 days |
| `groups.yml` (private repo) | git | on every change | infinite (git history) |
| Loki streams (audit log secondary sink) | Loki retention policy | continuous | 90 days |
| Promtail config | Ansible repo | on every change | infinite |

## pg_dump cron

A simple systemd timer on LXC 280 runs:

```bash
pg_dump rp_server | gzip > /mnt/nas/backups/rp-server/pg_dump-$(date +%F).sql.gz
find /mnt/nas/backups/rp-server -name 'pg_dump-*.sql.gz' -mtime +30 -delete
```

The NAS mount is read-write only for the backup user; a separate read-only
mount is used by the restore tooling.

## What is **not** backed up

- Ephemeral Tailscale auth-keys (regenerate on restore).
- Continuous-aggregate cache (`metric_samples_5min`) — rebuilt
  automatically from raw `metric_samples` after restore.
- `/var/lib/rp/queue.db` on each agent — local-only by design.

## Verifying backups

Run on a schedule via Healthchecks:

```bash
# Latest pg_dump exists and is non-empty
test $(find /mnt/nas/backups/rp-server -name 'pg_dump-*.sql.gz' \
       -mtime -1 -size +1M | wc -l) -ge 1

# PBS shows last snapshot < 36h old
pbs-client list-snapshots --limit 1 --vmid 280 | \
  jq -e '.[0].backup_time | (now - .) < 129600'
```

Both must pass nightly. Failure pages Telegram.

## Restore procedures

See [disaster recovery](disaster-recovery.md). Drill cadence is quarterly.
