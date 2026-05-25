-- F4 Schema Example INSERT/SELECT Queries
-- Demonstrates groups, ssh_keys, commands, agent_versions usage

-- =============================================================================
-- GROUPS
-- =============================================================================

-- Insert a group
INSERT INTO groups (name, description, access_users, auto_distribute_keys)
VALUES ('prod', 'Production hosts', ARRAY['ramon@monxas.casa', 'hermes@system'], TRUE);

-- Query groups
SELECT name, description, array_length(access_users, 1) as user_count, auto_distribute_keys
FROM groups
ORDER BY created_at DESC;

-- Expected output:
-- name  | description         | user_count | auto_distribute_keys
-- prod  | Production hosts    | 2          | t
-- family| Family hosts        | 1          | t
-- iarq  | Client hosts        | 1          | t
-- default| Default group      | 1          | f


-- =============================================================================
-- SSH KEYS
-- =============================================================================

-- Insert SSH key (assuming host exists with id '123e4567-e89b-12d3-a456-426614174000')
INSERT INTO ssh_keys (host_id, user_name, pubkey, fingerprint, algorithm)
VALUES (
    '123e4567-e89b-12d3-a456-426614174000',
    'root',
    'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAbCdEfGhIjKlMnOpQrStUvWxYz root@pmx-50',
    'SHA256:abcdefghijklmnopqrstuvwxyz0123456789ABC',
    'ed25519'
);

-- Query active (non-revoked) SSH keys for a host
SELECT id, user_name, fingerprint, algorithm, created_at
FROM ssh_keys
WHERE host_id = '123e4567-e89b-12d3-a456-426614174000'
  AND revoked_at IS NULL
ORDER BY created_at DESC;

-- Expected output:
-- id                                   | user_name | fingerprint           | algorithm | created_at
-- <uuid>                               | root      | SHA256:abcdef...      | ed25519   | 2026-05-25 ...

-- Query all keys grouped by host with revocation status
SELECT h.hostname, k.user_name, k.fingerprint,
       CASE WHEN k.revoked_at IS NULL THEN 'active' ELSE 'revoked' END as status
FROM ssh_keys k
JOIN hosts h ON k.host_id = h.id
ORDER BY h.hostname, k.created_at DESC;


-- =============================================================================
-- COMMANDS (Immutable Audit Log)
-- =============================================================================

-- Insert command record (server issues this when creating command)
INSERT INTO commands (
    host_id, issued_by, command_type, command_payload,
    server_signature, human_approved
)
VALUES (
    '123e4567-e89b-12d3-a456-426614174000',
    'ramon@monxas.casa',
    'exec_shell',
    '{"cmd": "systemctl restart nginx", "timeout_s": 30}'::jsonb,
    'ed25519:signature_base64_here',
    FALSE
);

-- Query recent commands for a host
SELECT id, issued_by, command_type, issued_at, completed_at,
       exit_code, human_approved, rejected_reason
FROM commands
WHERE host_id = '123e4567-e89b-12d3-a456-426614174000'
ORDER BY issued_at DESC
LIMIT 20;

-- Expected output:
-- id      | issued_by          | command_type | issued_at           | completed_at | exit_code | human_approved | rejected_reason
-- <uuid>  | ramon@monxas.casa  | exec_shell   | 2026-05-25 10:15:00 | NULL         | NULL      | f              | NULL

-- Query command audit trail for a specific user
SELECT h.hostname, c.command_type,
       c.command_payload->>'cmd' as command,
       c.issued_at, c.exit_code
FROM commands c
JOIN hosts h ON c.host_id = h.id
WHERE c.issued_by = 'ramon@monxas.casa'
  AND c.issued_at > now() - INTERVAL '7 days'
ORDER BY c.issued_at DESC;

-- Try UPDATE (should fail with trigger exception)
-- UPDATE commands SET exit_code = 0 WHERE id = '<uuid>';
-- ERROR:  commands table is append-only (audit log)


-- =============================================================================
-- AGENT VERSIONS
-- =============================================================================

-- Insert agent version compatibility info
INSERT INTO agent_versions (host_id, agent_version, api_compat_min, api_compat_max)
VALUES (
    '123e4567-e89b-12d3-a456-426614174000',
    '0.5.2',
    '0.5.0',
    '0.6.0'
);

-- Query hosts with version compatibility info
SELECT h.hostname, h.agent_version as enrolled_version,
       av.agent_version as current_version,
       av.api_compat_min, av.api_compat_max, av.last_check
FROM hosts h
LEFT JOIN agent_versions av ON h.id = av.host_id
ORDER BY h.hostname;

-- Expected output:
-- hostname | enrolled_version | current_version | api_compat_min | api_compat_max | last_check
-- pmx-50   | 0.5.1            | 0.5.2           | 0.5.0          | 0.6.0          | 2026-05-25 ...


-- =============================================================================
-- HOST GROUP FK CONSTRAINT
-- =============================================================================

-- Query hosts by group with group details
SELECT h.hostname, h.os, h.arch, g.description as group_desc,
       g.access_users, g.auto_distribute_keys
FROM hosts h
LEFT JOIN groups g ON h.group_name = g.name
WHERE h.group_name = 'prod'
ORDER BY h.hostname;

-- Expected output:
-- hostname | os    | arch   | group_desc       | access_users           | auto_distribute_keys
-- pmx-50   | linux | x86_64 | Production hosts | {ramon@monxas.casa...} | t
-- pmx-51   | linux | x86_64 | Production hosts | {ramon@monxas.casa...} | t


-- =============================================================================
-- CASCADE DELETES
-- =============================================================================

-- Deleting a host cascades to ssh_keys and agent_versions
-- DELETE FROM hosts WHERE id = '123e4567-e89b-12d3-a456-426614174000';
-- This will automatically delete:
--   - All ssh_keys with host_id matching
--   - agent_versions record with host_id matching
-- Commands remain (audit log, FK does not cascade)


-- =============================================================================
-- INDEXES USAGE
-- =============================================================================

-- These queries benefit from indexes:

-- idx_ssh_keys_host (partial index on non-revoked keys)
EXPLAIN SELECT * FROM ssh_keys WHERE host_id = '...' AND revoked_at IS NULL;

-- idx_commands_host_issued
EXPLAIN SELECT * FROM commands WHERE host_id = '...' ORDER BY issued_at DESC LIMIT 20;

-- idx_commands_issued_by
EXPLAIN SELECT * FROM commands WHERE issued_by = 'ramon@monxas.casa' ORDER BY issued_at DESC;
