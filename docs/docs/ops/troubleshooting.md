# Operations troubleshooting

A grab-bag of operational gotchas and how to diagnose them. For
agent-install errors see [common errors](../troubleshooting/common-errors.md);
for Windows-specific issues see [Windows Defender](../troubleshooting/windows-defender.md).

## Heartbeats arriving but no metrics

1. Confirm the agent version is ≥0.3 (`rp version`).
2. Check the WS channels:
   ```bash
   journalctl -u remote-pulse -f --since '5 min ago' | grep ws
   ```
3. On the server, query the metrics router:
   ```bash
   curl -fsS http://127.0.0.1:8080/v1/metrics/<host_id>/series
   ```

## Agent shows green but exec commands fail

Most likely a local-policy block. From the host:

```bash
sudo rp local status
sudo rp local evaluate exec_shell --payload='{"cmd":"echo hi"}' --group=$(rp status --field=group)
```

If the evaluation prints `deny: missing_flag /etc/rp/allow-remote-exec`, see
the [local-approval guide](../guide/local-approval.md).

## Clock-skew alert keeps firing

`rp_host_clock_skew_seconds > 120` means the agent and server clocks disagree.

1. On the host: `timedatectl status` (Linux) or `systemsetup -getusingnetworktime` (macOS).
2. Ensure NTP is running and reaching upstream.
3. As a workaround, the server uses `received_at` as source of truth for
   ordering, so dashboards remain consistent. The alert is informational.

## Postgres storage growing fast

Expected size at 50 hosts: ~15 GB. If you see >30 GB and fleet is similar:

1. Check `metric_samples` retention is enforced:
   ```sql
   SELECT * FROM timescaledb_information.policies WHERE hypertable_name='metric_samples';
   ```
2. Inspect continuous-aggregate freshness:
   ```sql
   SELECT * FROM timescaledb_information.continuous_aggregates;
   ```
3. Trigger compression:
   ```sql
   SELECT compress_chunk(c) FROM show_chunks('metric_samples', older_than => INTERVAL '7 days') c;
   ```

## `rp dash` connects but shows zero hosts

The user's `accessible_groups` is probably empty.

```bash
rp admin users show <email>
rp admin users update <email> --groups=family,iarq
```

## Tailscale identity header missing on a request

Verify `tailscale serve` is healthy:

```bash
tailscale serve status
```

If the proxy is down, FastAPI returns 401 to every non-bootstrap request.
Restart with:

```bash
systemctl restart tailscaled
tailscale serve --bg --https=443 / http://127.0.0.1:8080
```

## See also

- [Disaster recovery](disaster-recovery.md)
- [Common errors](../troubleshooting/common-errors.md)
