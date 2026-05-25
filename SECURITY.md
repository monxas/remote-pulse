# Security Policy

## Reporting a vulnerability

Found a vulnerability in Remote-Pulse? **Please do not open a public GitHub issue.**

**Contact:** security@monxas.casa (forwards to the maintainer)

**PGP key:** TBD (targeting v0.2.0 — for now, email is unencrypted but monitored)

### Disclosure timeline

We follow coordinated vulnerability disclosure (CVD):

1. **Acknowledgement:** Within 72 hours of report
2. **Initial assessment:** Within 7 days (severity classification, impact analysis)
3. **Fix or mitigation plan:** Within 30 days
4. **Public disclosure:** 90 days after fix deployed (or sooner if mutually agreed)

### Bug bounty

No formal bug bounty program (homelab scope, non-commercial). However:
- Responsible disclosures acknowledged in `SECURITY.md` acknowledgements section
- Critical findings may receive recognition in release notes

We appreciate security research conducted ethically and responsibly.

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

Responsible disclosers recognized here:

- *No public vulnerabilities reported yet (v0.1.0 pre-release)*

Thank you to all security researchers who help keep Remote-Pulse secure.

---

## Additional resources

- **Security audit report:** [docs/security/audit-2026-05-25.md](docs/security/audit-2026-05-25.md)
- **Security checklist:** [docs/security/checklist.md](docs/security/checklist.md)
- **Architecture security model:** [ADR-0008 §5](https://docs.monxas.casa/architecture/adr/ADR-0008-remote-pulse/) (defense-in-depth layers)
- **DR procedure:** ADR-0008 Appendix F (disaster recovery, key rotation)
