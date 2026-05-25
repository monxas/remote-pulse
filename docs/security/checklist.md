# Security Checklist — Remote-Pulse

**Last updated:** 2026-05-25 (v0.1.0 pre-release)  
**Owner:** F8-SECURITY (ADR-0008)

---

## Authentication & Authorization

- ✅ **HTTPS only public endpoints** — All HTTP redirected to HTTPS, Caddy enforces TLS 1.3
- ✅ **Tailscale identity for non-public endpoints** — `Tailscale-User-Login` header injected by `tailscale serve`, not spoofable
- ✅ **JWT enrollment tokens single-use + TTL 24h** — 256-bit random (HS512), bound to host fingerprint at first use
- ✅ **Ed25519 server signing for commands** — Server signs commands with Ed25519 private key, agent verifies with public key
- ✅ **Local-approval enforcement (defense-in-depth)** — Agent checks `/etc/rp/allow-remote-exec` before destructive ops
- ✅ **Telegram approval for destructive ops** — Human-in-the-loop via n8n webhook for prod/iarq groups

---

## Audit & Immutability

- ✅ **Audit log immutable (Postgres trigger)** — BEFORE UPDATE/DELETE/TRUNCATE triggers block modifications to `commands` table
- ✅ **Dual-sink audit trail** — Commands logged to Postgres + Loki (promtail scraping structured logs)
- ✅ **Structured logging** — JSON logs with `structlog` (timestamped, context-enriched)

---

## Network & Transport Security

- ✅ **Rate-limit /v1/enroll (10 req/min/IP)** — Caddy reverse proxy enforces rate limiting on enrollment endpoint
- ✅ **Security headers (HSTS, X-Frame-Options, CSP)** — Middleware adds security headers to all responses:
  - `Strict-Transport-Security: max-age=31536000; includeSubDomains`
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `Referrer-Policy: no-referrer`
  - `Content-Security-Policy: default-src 'self'; ...` (HTMX + uPlot compatible)
- ✅ **Tailscale ACL default-deny** — Agents cannot reach other agents (no lateral movement)

---

## Secrets & Dependency Management

- ✅ **Secrets scan (trufflehog)** — CI enforces full git history scan with `--only-verified` flag
- ✅ **Dependency vulnerability scan (Dependabot)** — Weekly automated PRs for security updates
- ✅ **Static analysis (semgrep + bandit)** — Security rulesets in CI (p/security-audit, p/owasp-top-ten, p/python)
- ✅ **JWT secret rotation procedure** — `scripts/rotate-jwt-secret.sh` (yearly cadence or post-leak)
- ✅ **No hardcoded secrets** — All secrets loaded from environment variables or SOPS-encrypted files

---

## Software Supply Chain

- ✅ **SHA256 checksums published** — `SHA256SUMS` file in GitHub releases
- ✅ **Cosign keyless signing** — All release binaries signed with GitHub Actions OIDC identity
- ⚠️ **Code signing pendiente (Windows EV cert ~$300/yr)** — Deferred to v0.2.0 (budget approval required)
- ⚠️ **macOS notarization** — Deferred to v0.2.0 (Apple Developer Program $99/yr)

**Verification (manual):**
```bash
# Verify SHA256 checksum
sha256sum -c SHA256SUMS

# Verify cosign signature (requires cosign CLI)
cosign verify-blob --bundle rp-linux-x64.sig \
  --certificate-identity-regexp "https://github.com/monxas/remote-pulse" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  rp-linux-x64
```

---

## Testing & Validation

- ✅ **Audit log immutability test** — `test_audit_log_immutability.py` (Postgres triggers validated)
- ✅ **Rate limit test** — `test_rate_limit.py` (documents expected Caddy behavior)
- ✅ **Enrollment flow test** — `test_enroll.py` (JWT validation, replay protection)
- ✅ **Tailscale identity test** — `test_tailscale_identity.py` (header injection)
- ✅ **Command signing test** — `test_signing.py` (Ed25519 signature verification)

---

## Incident Response & DR

- ✅ **DR procedure documented** — ADR-0008 Appendix F (LXC restore, fleet re-auth, key rotation)
- ✅ **DR drill cadence** — Quarterly minimum (trimestral), or semi-annually if <0 incidents in 6 months
- ⚠️ **Pentest pendiente (post v1.0 GA)** — External firm, budget $2k-5k, yearly cadence

---

## Deployment & Configuration

- ✅ **Postgres user limited privileges** — Server DB user has no DROP/ALTER permissions on production
- ✅ **Systemd hardening** — Agent service runs with `PrivateTmp=true`, `ProtectHome=read-only`
- ✅ **Minimal container privileges** — LXC 280 unprivileged, no kernel module loading
- ✅ **Secrets at rest encrypted** — Server config (`/etc/rp/server.env`) has mode 0600, owned by root

---

## Monitoring & Alerting

- ✅ **Prometheus metrics exposed** — `/metrics` endpoint (fleet health, command success rate)
- ✅ **Grafana dashboards** — Real-time fleet status, sparklines, audit log queries
- ✅ **Loki audit log ingestion** — Structured logs from server + agents
- ✅ **Healthchecks.io integration** — Dead man's switch for critical hosts (heartbeat <15min)
- ✅ **Telegram alerts** — n8n webhook forwards critical events (host down, destructive command approval)

---

## Known Limitations (v0.1.0 pre-release)

### ⚠️ Deferred to v0.2.0 (3-month milestone)
- **Windows Authenticode signing** — Budget $300/yr (DigiCert/Sectigo EV cert)
- **macOS notarization** — Budget $99/yr (Apple Developer Program)
- **Application-level rate limiting** — SlowAPI middleware as Caddy fallback
- **SBOM generation** — CycloneDX BOM published with releases

### ⚠️ Deferred to v1.0 GA (6-month milestone)
- **WAF rules** — Cloudflare Access fronting Caddy (DDoS protection, bot detection)
- **Penetration test** — External firm ($2k-5k budget)
- **Bug bounty program** — Community scope, acknowledgements wall
- **Security.txt + PGP key** — RFC 9116 compliance

### ⚠️ Ongoing maintenance
- **Quarterly dependency audits** — Beyond automated Dependabot (manual review of transitive deps)
- **Annual penetration test** — Post-v1.0, after major version bumps
- **CVE monitoring** — GitHub Security Advisories (already enabled)
- **Incident response playbook** — SIRT-style runbook for compromise scenarios

---

## Compliance & Standards

- ✅ **OWASP Top 10 coverage** — Semgrep ruleset `p/owasp-top-ten` in CI
- ✅ **CWE Top 25 mitigations** — Static analysis (Bandit) covers injection, XSS, auth bypass
- ⚠️ **SOC 2 Type II** — Not applicable (homelab scope, no commercial SLA)
- ⚠️ **ISO 27001** — Not applicable (individual project, not organizational ISMS)

---

## Review Cadence

- **Pre-release (v0.1.0):** This checklist (2026-05-25)
- **v0.2.0 milestone:** Update with code signing status, SBOM, application-level rate limit
- **v1.0 GA:** Update with pentest results, WAF config, bug bounty program
- **Ongoing:** Quarterly review, update after security incidents or major dependency changes

---

**Approved by:** F8-SECURITY Agent  
**Date:** 2026-05-25  
**Next review:** v0.2.0 release (target 2026-08-25)
