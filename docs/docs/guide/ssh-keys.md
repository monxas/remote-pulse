# SSH key lifecycle

Remote-Pulse manages SSH public keys for the fleet **declaratively**: the
server keeps an inventory, hosts only ever generate their own private keys,
and `authorized_keys` is reconciled from group membership.

```mermaid
flowchart LR
    A[Agent boots] -->|ssh-keygen ed25519| K[/etc/rp/host_key]
    K -->|POST /v1/keys| S[(Server: ssh_keys table)]
    G[groups.yml] --> S
    S -->|POST /v1/keys/distribute/prod| D[Compute group<br/>authorized_keys]
    D -->|GET /v1/keys/authorized/{host_id}| AG[Agent timer 5min]
    AG -->|atomic write| F[/etc/rp/authorized_keys.d/managed]
    F --> SSHD[sshd_config<br/>AuthorizedKeysFile]
```

## Principles

- **Private keys never leave the host.** Only public keys are ever sent to
  the server.
- **Soft revocation.** Keys are marked `revoked_at` in the database, not
  deleted, so the audit trail survives compromise investigations.
- **Idempotent sync.** The agent computes the SHA256 of the candidate
  `authorized_keys` file and only writes if it differs.
- **Atomic writes.** Temp file plus rename, so a crash mid-write never
  produces a half-written `authorized_keys`.
- **Local key preserved.** The agent never touches `~/.ssh/authorized_keys`.
  sshd reads both the user file and the managed file via
  `AuthorizedKeysFile`.

## Groups

Groups are declared in `homelab-infra/services/remote-pulse-server/config/groups.yml`
(server-side, private repo). Example:

```yaml
groups:
  prod:
    description: Production hosts
    members: [pmx-50, pmx-51, vm-208, lxc-101, lxc-100]
    access: [ramon@monxas.casa, hermes@monxas.casa]
    auto_distribute: true
  family:
    members: [carmelo, padre-laptop]
    access: [ramon@monxas.casa]
  iarq:
    members: [iarq-rag, iarq-locator]
    access: [ramon@monxas.casa]
```

`access` is the list of users whose pubkeys end up in the merged
`authorized_keys` for hosts in the group.

## Bootstrap

The installer runs the equivalent of:

```bash
sudo rp keys init           # generate keypair, register pubkey
sudo rp keys configure-sshd # add AuthorizedKeysFile entry, reload sshd
sudo rp keys sync           # pull initial authorized_keys
```

A `remote-pulse-keys-sync.timer` (systemd) re-runs `rp keys sync` every
5 minutes to keep `authorized_keys` current after group changes.

## Rotation

```bash
sudo rp keys rotate --reason="quarterly rotation"
```

This is **non-destructive**: the new key is registered, then the old one is
marked `revoked_at`. The next `keys sync` cycle on every host in the group
drops the revoked key from their `authorized_keys`. Lockout window: under
60 seconds in the default configuration.

## Revocation (admin)

From a workstation:

```bash
# Revoke a specific key
rp admin keys revoke SHA256:W+7BK0GIxg0iUXb4rxNZFslWzr+iqOMlvUxOqC5LPco \
  --reason="laptop lost"

# Re-distribute to push the revocation
rp admin keys distribute prod
```

The revoked key disappears from every host in the group on the next sync.

## Safety nets

- Each host keeps `~/.ssh/authorized_keys` (user file) intact. If the
  managed file ever becomes corrupt, classic SSH still works.
- `rp keys distribute` defaults to dry-run preview. Pass `--apply` to
  actually push.
- The `commands` table logs every mutation (`key_register`, `key_revoke`,
  `keys_distribute`) and the server triggers a Telegram alert on revoke.

## Underlying API

If you prefer raw HTTP, see [REST API reference](../reference/api.md#ssh-keys).
The agent uses the same endpoints — there is no privileged channel.
