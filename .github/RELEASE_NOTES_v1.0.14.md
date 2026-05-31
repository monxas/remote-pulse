# Remote-Pulse v1.0.14 — QoL polish pass on v1.0.13

Patch release. No alembic migration. No new features — pure UX polish surfaced by auditing v1.0.13 against the QoL standard.

## Why this release exists

After shipping v1.0.0 → v1.0.13 at speed (14 releases in two days, 32 sub-agents), an audit caught three places where the backend was correct but the UI was a placeholder. The pattern: typing where a list would do, single-click confirms for destructive ops, capability-blind gating. This release closes those before adding more surface.

## Highlights

- **Webhook `group_filter`** is now a multi-select pill picker reading from `/v1/dash/settings/groups`. No more comma-separated typing of group names that might not even exist. Empty state when no groups are in the system; helper text reflects the current selection.
- **Retention "Purge now"** confirmation requires typing `DELETE` verbatim before the destructive button arms. Matches the high-friction convention from bulk-delete users/groups in v1.0.11. Irreversible operations should not be one click away.
- **Host detail "Delete" button** is now capability-gated, not role-gated. Operators holding a `host.delete` grant whose scope matches the host's group (or `*`) now see the button instead of having an invisible feature. `/auth/me` now ships the user's row-level permissions in the boot payload so the SPA gate stays in lockstep with the server's `user_has_permission` helper.

## Changes

### Server

- `feat(server-auth)` `GET /auth/me` response gains an additional `permissions: list[{action, scope}]` field. Always present (empty list when the user is admin — admins bypass server-side, the client mirrors). Adds one indexed SELECT against `user_permissions` per `/auth/me` call for non-admin users; admins pay no DB cost.

### Dashboard SPA

- `feat(web-stores)` `userStore.hasPermission(action, scope?)` helper mirrors the server-side check: admin → true, otherwise look for a matching `{action, scope}` grant with `*` or exact-group match. UX-only gate; server remains source of truth.
- `feat(web-webhooks)` Create-webhook modal's group filter is a pill multi-select (was free-text comma-separated input). Reads from live groups list. New `data-testid="wh-group-{name}"` for E2E.
- `feat(web-retention)` Purge-now dialog requires typing `DELETE` to arm the destructive button. New `data-testid="retention-purge-confirm-input"`.
- `feat(web-host)` Host detail Danger zone now visible to operators with the `host.delete` capability (admins as before).

### Agent

- `chore` `__version__` + `pyproject.toml` → `1.0.14` (lockstep with server).

## Upgrade

```sh
cd /opt/rp/source
git pull
scripts/build_dashboard.sh
systemctl restart rp-server
```

No alembic migration.

## Verifying

```sh
curl -sS https://rp.monxas.casa/health
# {"status":"healthy","version":"1.0.14"}

# /auth/me now includes "permissions" (empty list for admin, populated for operators)
curl -sS https://rp.monxas.casa/auth/me --cookie "rp_session=..." | jq '.permissions'
```

In the dashboard:
- `/webhooks` → "New webhook" → "Group filter (optional)" now shows pills for each existing group.
- `/settings` → Retention tab → "Purge now" → type DELETE → button enables.
- As an operator with a `host.delete:prod` grant, `/hosts/[id]` for any prod host now shows the Danger zone.

## Known follow-ups (v1.0.15+)

The audit also surfaced these as significant but deferred:
- QR code on the magic-link enroll result card (Family Hub Tablet share use case).
- PermissionsDialog `scope` chip multi-select picker instead of `<Input>`+`<datalist>`.
- BulkIssueCommandDialog "Cancel remaining" mid-flight button.
- Webhook URL one-click integration templates (Discord / Slack / n8n).
- Stats page `audit_events_total` sparkline.
- Audit page action chips sorted by frequency.
