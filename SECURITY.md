# Security Policy

## Reporting a vulnerability

Found a vulnerability in Remote-Pulse? **Please do not open a public GitHub issue.**

Email: **security@monxas.casa** (forwards to the maintainer).

Expected response time: 72 hours acknowledgement, 30 days fix or mitigation plan.

## Scope

The Remote-Pulse public agent is in scope. The private server lives in the homelab and is not directly exposed; report any inferred server-side issues anyway (e.g. protocol-level flaws).

In scope:
- Agent: install scripts (`scripts/install.sh`, `scripts/install.ps1`), the `rp` CLI binary, the daemon.
- Bootstrap endpoint behaviour observable from `rp.monxas.casa/install`.
- Tailscale identity injection assumptions.
- JWT enrollment token mechanics.
- SSH key lifecycle (post F4 release).

Out of scope:
- DoS via crafted enrollment tokens against rate-limited public endpoints (already rate-limited).
- Issues that require root access to a host already enrolled (root is trusted by design).
- Tailscale Inc. infrastructure (report upstream).

## Security model summary

See [ADR-0008 §5 Auth model](https://docs.monxas.casa/architecture/adr/ADR-0008-remote-pulse/) and Appendix E (Tailscale ACL) and Appendix F (DR procedure).

Three auth layers:

1. **Tailscale identity** — agents authenticate via `Tailscale-User-Login` header injected by `tailscale serve`. Not spoofable.
2. **JWT enrollment tokens** — single-use, 24h TTL, bound to host fingerprint at first use. Issued by the server admin.
3. **PocketID OIDC** — humans accessing the web dashboard.

Defense-in-depth (review C3 of ADR-0008):

- Agent enforces local-policy `/etc/rp/allow-remote-exec`, `/etc/rp/restart-whitelist`, etc. A compromised server cannot escalate to destructive ops in `prod`/`iarq` groups without these local flags **plus** Telegram approval routed through n8n.
- Audit log is append-only (Postgres trigger blocks UPDATE/DELETE) and dual-sinked to Loki for forensics if the database itself is compromised.
- Updates use canary deploys with auto-rollback to N-1 binary.

## Supported versions

Pre-alpha. Once v1.0.0 ships, N-2 deprecation policy applies (see ADR-0008 Appendix G).

## Acknowledgements

Will list responsible disclosers here once we get any.
