# Security model

Remote-Pulse uses a **3-layer auth model** plus **defense-in-depth** at the
agent. This page documents both, plus the JWT signing key rotation
procedure.

## Layer 1 — Tailscale identity (agents)

When the data plane is up, agent requests cross `tailscale serve` on the
server. The Tailscale daemon adds non-spoofable identity headers:

- `Tailscale-User-Login` — device owner.
- `Tailscale-User-Name` — display name.

FastAPI extracts these via a dependency. Requests arriving at `0.0.0.0:8443`
(the public bootstrap port) do **not** carry these headers and are rejected
unless they target an explicit allowlist endpoint.

**Threat model:** an attacker would need to either (a) compromise the
Tailscale control plane, or (b) MITM inside a tailnet, both of which are
mitigated by WireGuard and Tailscale's own auditing.

## Layer 2 — Enrollment JWT (bootstrap)

For the brief moment when a host is not yet on the tailnet, it must call
`POST /v1/enroll` publicly. The token is:

- **Single-use** (`max_uses=1` by default).
- **Time-bound** (`exp` 24 hours).
- **Bound on first use** to a `host_fingerprint` (TPM or `/etc/machine-id`).
- **Signed HS512** with `RP_ENROLLMENT_SECRET` (stored in SOPS).

If the token is leaked but already used, the binding prevents re-use. If
leaked and unused, the admin can revoke from the CLI:

```bash
rp admin enroll-revoke <token_jti>
```

Caddy rate-limits `/v1/enroll` to 10 req/min/IP.

## Layer 3 — PocketID OIDC (humans)

The web dashboard sits behind Caddy `forward_auth` → PocketID. After OIDC,
Caddy forwards `X-Forwarded-User` to the FastAPI app, which resolves it to
a `user_id` and a role (`admin` / `operator` / `viewer`).

PocketID supports passkeys; that is the default flow for family/clients.

## Defense-in-depth — agent-side local-approval

This is the **C3 mitigation** from the ADR review. Even if the entire server
is compromised — attacker holds the Ed25519 signing key, can forge any
command — they cannot execute destructive operations on `prod`/`iarq` hosts
without:

1. A flag file under `/etc/rp/` (root-only, locally created).
2. (For the worst commands) a Telegram approval ack inside 5 minutes.

See the [local-approval enforcement guide](../guide/local-approval.md) for
the full decision flow, per-command-type policy matrix, and CLI surface.

## Audit log

Every server-issued command, regardless of outcome, lands in two places:

| Sink | Why |
|------|-----|
| Postgres `commands` table | Primary, queryable, append-only via DB trigger that raises on UPDATE/DELETE. |
| Loki `{job="remote-pulse"}` | Secondary forensics sink. Survives Postgres compromise. |

The trigger:

```sql
CREATE OR REPLACE FUNCTION block_command_mutations() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'commands table is append-only';
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER commands_immutable
    BEFORE UPDATE OR DELETE ON commands
    FOR EACH ROW EXECUTE FUNCTION block_command_mutations();
```

A `commands_archive` table without the trigger receives rows older than
1 year via a server-side cron.

## Ed25519 signing key

The server signs every command sent to agents with an Ed25519 private key.
Agents have the public key pre-installed in `/etc/rp/server.pub` (delivered
at enrollment, pinned TOFU thereafter).

### Rotation procedure

If the signing key is suspected compromised (see also
[DR procedure](../ops/disaster-recovery.md#case-f2-compromise-of-ed25519-signing-key)):

1. **Generate new keypair on LXC 280:**
   ```bash
   rp admin rotate-signing-key
   ```
   This generates `server.key.new` / `server.pub.new` and signs the new
   public key with the **old** key, producing a `rotation-envelope.json`.
2. **Mark all sessions as `requires_reauth`** in Postgres.
3. **Push new pubkey to agents** via the tailnet:
   ```
   POST /v1/agent/rotate-trust
   { "new_pubkey": "...",
     "envelope_signed_by_old": "..." }
   ```
   The agent verifies the envelope against the previously trusted key. If
   it matches, the new key is pinned and the old one purged.
4. **Optional Telegram confirm.** For belt-and-braces, agents may require a
   human ack before accepting the new key. Configurable via
   `/etc/rp/require-rotation-confirm`.
5. **Re-issue any pending commands** under the new key. Old pending commands
   are dropped from the queue.
6. **Audit log** records the rotation event in `commands` with type
   `signing_key_rotated` so future forensics can correlate.

### Rotation cadence

- **Routine:** none mandated; rotate on suspected compromise only.
- **Test rotation:** part of the F8 DR drill (quarterly), validates the
  envelope chain works end-to-end against staging agents.

## Common questions

**Q: Why not mTLS?** PKI plus cert rotation across heterogeneous hosts is
operationally heavy. Tailscale identity + JWT covers it. If future
compliance demands crypto-layer defense-in-depth, mTLS can be added on top
of the existing Tailscale transport without breaking anything.

**Q: What about an attacker with root on a `prod` host?** The threat model
treats root on a host as trusted (the agent runs as root to manage `/etc/rp/`
and sshd). Compromise of one host does **not** escalate to others — see the
no-lateral-movement ACL in [the Tailscale section](tailscale.md#acl-policy).

**Q: Can the server read host files?** Only via `file_read`, which requires
`/etc/rp/read-allowlist` patterns to match. Default is empty.

**Q: How fast can a compromised key be revoked from the fleet?** Under 60 s
for hosts with active heartbeats (commands fail signature check
immediately). Offline hosts get the new trust at next reconnect.

## Reporting vulnerabilities

See [`SECURITY.md`](https://github.com/monxas/remote-pulse/blob/main/SECURITY.md).
Short version: email `security@monxas.casa`, do not open public issues.
