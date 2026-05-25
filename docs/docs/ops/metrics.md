# Monitoring metrics

The server exposes Prometheus metrics on `/metrics` (tailnet-only). They
power both the Grafana `Remote-Pulse Fleet` dashboard and the alerting
rules.

## Host metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `rp_host_up` | gauge | `host`, `group` | 1 if last heartbeat ≤60 s ago, 0 otherwise. |
| `rp_host_last_seen_seconds` | gauge | `host` | Seconds since last heartbeat. |
| `rp_host_cpu_pct` | gauge | `host` | Current CPU utilisation (last sample). |
| `rp_host_mem_pct` | gauge | `host` | Current memory utilisation. |
| `rp_host_disk_used_pct` | gauge | `host`, `mount` | Disk utilisation per mount. |
| `rp_host_net_rx_bps` | gauge | `host`, `iface` | RX throughput last 60 s. |
| `rp_host_net_tx_bps` | gauge | `host`, `iface` | TX throughput last 60 s. |
| `rp_host_uptime_seconds` | counter | `host` | Reported by the agent. |
| `rp_host_clock_skew_seconds` | gauge | `host` | `received_at − agent_ts`. |
| `rp_host_agent_version_info` | gauge | `host`, `version` | 1 for the agent's reported version. |

## Server metrics

| Metric | Type | Description |
|--------|------|-------------|
| `rp_server_heartbeats_received_total` | counter | Cumulative heartbeats accepted. |
| `rp_server_commands_issued_total` | counter (labels: `type`, `result`) | Commands sent to agents. |
| `rp_server_commands_rejected_total` | counter (labels: `reason`) | Rejections (`signature_invalid`, `local_policy_deny`, …). |
| `rp_server_enrollments_total` | counter | Successful enrollments. |
| `rp_server_websocket_clients` | gauge | Active WS connections. |
| `rp_server_db_connection_pool_used` | gauge | Postgres pool utilisation. |
| `rp_server_postgres_storage_bytes` | gauge | DB size on disk. |

## Recommended alerting rules

```yaml
groups:
  - name: remote-pulse
    rules:
      - alert: RP_HostDown
        expr: rp_host_up == 0
        for: 3m
        labels: { severity: warning }
        annotations:
          summary: "Host {{ $labels.host }} has not heartbeat in >3 min"

      - alert: RP_ClockSkew
        expr: abs(rp_host_clock_skew_seconds) > 120
        for: 5m
        labels: { severity: info }

      - alert: RP_CommandRejectionSpike
        expr: rate(rp_server_commands_rejected_total[5m]) > 0.5
        for: 5m
        labels: { severity: critical }
        annotations:
          summary: "Spike in rejected commands — possible signing-key issue"

      - alert: RP_PostgresStorageHigh
        expr: rp_server_postgres_storage_bytes / (50 * 1024 * 1024 * 1024) > 0.85
        for: 30m
        labels: { severity: warning }

      - alert: RP_EnrollmentBurst
        expr: rate(rp_server_enrollments_total[10m]) > 1
        for: 10m
        labels: { severity: info }
        annotations:
          summary: "Enrollment burst — confirm expected"
```

The Grafana dashboard JSON ships in `homelab-infra/ansible/roles/grafana_dashboards/files/remote-pulse-fleet.json`.

## See also

- [Disaster recovery](disaster-recovery.md)
- [Components — observability](../architecture/components.md#observability-reused-stack)
