# F4-KEYS: SSH Key Lifecycle Examples

## Server Endpoints

### 1. Register SSH Key (Agent POST)

```bash
curl -X POST http://localhost:8080/v1/keys \
  -H "Content-Type: application/json" \
  -d '{
    "host_id": "550e8400-e29b-41d4-a716-446655440000",
    "user_name": "root",
    "pubkey": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl rp-agent-pmx-50",
    "fingerprint": "SHA256:W+7BK0GIxg0iUXb4rxNZFslWzr+iqOMlvUxOqC5LPco",
    "algorithm": "ed25519"
  }'
```

Response:
```json
{
  "id": "123e4567-e89b-12d3-a456-426614174000",
  "host_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_name": "root",
  "pubkey": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl rp-agent-pmx-50",
  "fingerprint": "SHA256:W+7BK0GIxg0iUXb4rxNZFslWzr+iqOMlvUxOqC5LPco",
  "algorithm": "ed25519",
  "created_at": "2024-05-25T12:00:00Z",
  "revoked_at": null,
  "revoked_reason": null
}
```

### 2. List Keys

```bash
curl http://localhost:8080/v1/keys?group=prod \
  -H "Tailscale-User-Login: ramon@monxas.casa"
```

### 3. Revoke Key

```bash
curl -X DELETE "http://localhost:8080/v1/keys/SHA256:W+7BK0GIxg0iUXb4rxNZFslWzr+iqOMlvUxOqC5LPco?reason=key+rotation" \
  -H "Tailscale-User-Login: ramon@monxas.casa"
```

### 4. Distribute Keys (Generate authorized_keys for group)

```bash
curl -X POST http://localhost:8080/v1/keys/distribute/prod \
  -H "Tailscale-User-Login: ramon@monxas.casa"
```

Response:
```json
{
  "group": "prod",
  "content": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl rp-managed-root@550e8400-e29b-41d4-a716-446655440000\n",
  "host_count": 12,
  "key_count": 12,
  "generated_at": "2024-05-25T12:05:00Z"
}
```

### 5. Get Authorized Keys for Host (Agent polling)

```bash
curl http://localhost:8080/v1/keys/authorized/550e8400-e29b-41d4-a716-446655440000
```

Response:
```json
{
  "content": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl rp-managed-root@550e8400-e29b-41d4-a716-446655440000\n",
  "sha256": "abc123def456..."
}
```

## Agent CLI Commands

### Initialize and Register Key

```bash
# Generate ed25519 keypair and register with server
sudo rp keys init
```

Output:
```
Host key: /etc/rp/host_key
Fingerprint: SHA256:W+7BK0GIxg0iUXb4rxNZFslWzr+iqOMlvUxOqC5LPco

✓ Key registered with server
  Key ID: 123e4567-e89b-12d3-a456-426614174000
  Created: 2024-05-25T12:00:00Z
```

### Check Key Status

```bash
rp keys status
```

Output:
```
Local Key:
  Path: /etc/rp/host_key
  Fingerprint: SHA256:W+7BK0GIxg0iUXb4rxNZFslWzr+iqOMlvUxOqC5LPco
  Algorithm: ssh-ed25519

Server Status:
  Registered: Yes
  Key ID: 123e4567-e89b-12d3-a456-426614174000
  Created: 2024-05-25T12:00:00Z
```

### Sync Authorized Keys

```bash
# Pull authorized_keys from server (idempotent)
sudo rp keys sync
```

Output:
```
✓ Authorized keys updated: /etc/rp/authorized_keys.d/managed
```

### Rotate Key

```bash
# Generate new key, register, revoke old, sync
sudo rp keys rotate --reason "scheduled rotation"
```

Output:
```
✓ New key registered: SHA256:NewFingerprint...
✓ Old key revoked: SHA256:W+7BK0GIxg0iUXb4rxNZFslWzr+iqOMlvUxOqC5LPco
✓ Authorized keys synced
```

### Configure sshd

```bash
# Add /etc/rp/authorized_keys.d/managed to sshd_config
sudo rp keys configure-sshd
```

Output:
```
✓ sshd configured and reloaded
  Backup: /etc/ssh/sshd_config.rp-backup
```

## Admin CLI (Server-Side)

### Apply groups.yml Configuration

```bash
# Sync groups from config/groups.yml to database
cd server
uv run python -m rp_server.admin groups apply
```

Output:
```
Created group: prod
Created group: family
Created group: iarq

✓ Applied 4 groups
```

### List Groups

```bash
uv run python -m rp_server.admin groups list
```

Output:
```
Name     Description                      Access Users         Auto Dist  Created
-------  -------------------------------- -------------------- ---------- ----------
prod     Production hosts                 ramon@monxas.casa    Yes        2024-05-25
family   Family hosts                     ramon@monxas.casa    Yes        2024-05-25
iarq     iarquitectos.com client hosts    ramon@monxas.casa    Yes        2024-05-25
```

### List SSH Keys

```bash
uv run python -m rp_server.admin keys list --group=prod
```

### Revoke Key

```bash
uv run python -m rp_server.admin keys revoke SHA256:fingerprint --reason "compromised"
```

## Systemd Timer (Auto-Sync)

Install with timer enabled:

```bash
cd packaging/linux
sudo ./install-systemd.sh --with-keys-sync
```

This installs:
- `remote-pulse-keys-sync.service` (oneshot)
- `remote-pulse-keys-sync.timer` (every 5min)

Check status:
```bash
systemctl status remote-pulse-keys-sync.timer
systemctl list-timers remote-pulse-keys-sync.timer
```

Manual trigger:
```bash
sudo systemctl start remote-pulse-keys-sync.service
```

## Flow Example: Onboard New Host

1. **Server:** Create enrollment token (F1)
2. **Host:** Run bootstrap script (installs agent)
3. **Host:** `rp keys init` generates and registers SSH key
4. **Host:** `rp keys configure-sshd` configures sshd
5. **Host:** `rp keys sync` pulls authorized_keys from server
6. **Admin:** Verify key registered: `uv run python -m rp_server.admin keys list`
7. **Timer:** Auto-syncs every 5min to keep authorized_keys current

## Security Model

- **Private keys never leave host**: Only pubkeys sent to server
- **Server custody**: Server maintains inventory, distributes declaratively
- **Soft revocation**: Keys marked `revoked_at`, not deleted (audit trail)
- **Idempotent sync**: Agent only writes if SHA256 differs
- **Atomic writes**: Temp file + rename to avoid partial writes
- **Audit log**: All mutations logged (TODO: Postgres + Loki double sink)
- **Telegram alerts**: Key rotation/revocation triggers n8n webhook (TODO: F4 implementation)
