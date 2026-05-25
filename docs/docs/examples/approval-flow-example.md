# Telegram Approval Flow Examples

**F4-6**: Example curl commands for testing the Telegram approval flow end-to-end.

## Setup

```bash
# Server URL (adjust based on environment)
export SERVER_URL="http://192.168.0.280:8000"

# n8n webhook URL
export N8N_WEBHOOK="http://192.168.0.200:5678/webhook/rp-approval"
```

## Example 1: Manual Approval Request

Test the webhook delivery without creating a real command.

```bash
# Fire webhook directly to n8n
curl -X POST "$N8N_WEBHOOK" \
  -H "Content-Type: application/json" \
  -d '{
    "event": "approval_required",
    "command_id": "12345678-1234-1234-1234-123456789abc",
    "command_type": "reboot",
    "command_payload": {"delay_s": 30},
    "host_hostname": "test-host",
    "host_group": "prod",
    "issued_by": "admin@monxas.casa",
    "issued_at": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'",
    "approval_token": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "approval_url_accept": "'"$SERVER_URL"'/v1/admin/commands/approve/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "approval_url_reject": "'"$SERVER_URL"'/v1/admin/commands/reject/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "expires_at": "'$(date -u -v+5M +%Y-%m-%dT%H:%M:%SZ)'"
  }'
```

**Expected**: Telegram message appears with inline buttons [Approve / Reject].

## Example 2: Create Command + Request Approval

```bash
# 1. Create a command (assuming host_id known)
export HOST_ID="abcdef12-3456-7890-abcd-ef1234567890"

RESPONSE=$(curl -s -X POST "$SERVER_URL/v1/admin/commands" \
  -H "Content-Type: application/json" \
  -d '{
    "host_id": "'"$HOST_ID"'",
    "command_type": "reboot",
    "command_payload": {"delay_s": 30},
    "timeout_s": 60,
    "expires_in_s": 60
  }')

echo "$RESPONSE" | jq .

# Extract command_id
export COMMAND_ID=$(echo "$RESPONSE" | jq -r '.id')

# 2. Request approval for the command
APPROVAL_RESPONSE=$(curl -s -X POST "$SERVER_URL/v1/admin/commands/$COMMAND_ID/request-approval")

echo "$APPROVAL_RESPONSE" | jq .

# Extract approval_token
export APPROVAL_TOKEN=$(echo "$APPROVAL_RESPONSE" | jq -r '.approval_token')

echo "Command ID: $COMMAND_ID"
echo "Approval Token: $APPROVAL_TOKEN"
```

## Example 3: Approve Command

Simulate clicking the "Approve" button in Telegram.

```bash
# Approve command
curl -X POST "$SERVER_URL/v1/admin/commands/approve/$APPROVAL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "approver_id": "ramonkawa",
    "reason": "Manual approval via curl"
  }' | jq .
```

**Expected response**:
```json
{
  "status": "approved",
  "command_id": "12345678-1234-1234-1234-123456789abc",
  "executed": false,
  "message": "Command approved by ramonkawa"
}
```

## Example 4: Reject Command

```bash
# Reject command
curl -X POST "$SERVER_URL/v1/admin/commands/reject/$APPROVAL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "approver_id": "ramonkawa",
    "reason": "Not safe to reboot now"
  }' | jq .
```

**Expected response**:
```json
{
  "status": "rejected",
  "command_id": "12345678-1234-1234-1234-123456789abc",
  "executed": false,
  "message": "Command rejected by ramonkawa: Not safe to reboot now"
}
```

## Example 5: List Pending Approvals

```bash
# List all pending approvals
curl -s "$SERVER_URL/v1/admin/commands/pending-approval" | jq .
```

**Expected response**:
```json
[
  {
    "command_id": "12345678-1234-1234-1234-123456789abc",
    "command_type": "reboot",
    "host_hostname": "pmx-50",
    "host_group": "prod",
    "issued_by": "admin@monxas.casa",
    "issued_at": "2026-05-25T14:30:00Z",
    "approval_requested_at": "2026-05-25T14:30:05Z",
    "expires_at": "2026-05-25T14:35:05Z"
  }
]
```

## Example 6: Test Expired Token

```bash
# Wait 5+ minutes after requesting approval, then try to approve
sleep 301  # 5min 1sec

curl -X POST "$SERVER_URL/v1/admin/commands/approve/$APPROVAL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "approver_id": "ramonkawa"
  }' | jq .
```

**Expected response**:
```json
{
  "detail": "Approval token expired (TTL 5min)"
}
```
**Status code**: 403

## Example 7: Test Double Approval

```bash
# Approve once
curl -X POST "$SERVER_URL/v1/admin/commands/approve/$APPROVAL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"approver_id": "ramonkawa"}' | jq .

# Try to approve again (token already cleared)
curl -X POST "$SERVER_URL/v1/admin/commands/approve/$APPROVAL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"approver_id": "ramonkawa"}' | jq .
```

**Second response**:
```json
{
  "detail": "Approval request not found or already processed"
}
```
**Status code**: 404

## Example 8: Query Command Status

```bash
# Check command details after approval
curl -s "$SERVER_URL/v1/admin/commands/$COMMAND_ID" | jq .
```

**Expected fields**:
```json
{
  "id": "12345678-1234-1234-1234-123456789abc",
  "command_type": "reboot",
  "human_approved": true,
  "approved_by": "telegram:ramonkawa",
  "rejected_reason": null,
  ...
}
```

## Example 9: Full Integration Test

Complete flow from command creation to approval.

```bash
#!/bin/bash
set -e

SERVER_URL="http://192.168.0.280:8000"
HOST_ID="your-host-id-here"

echo "1. Creating command..."
CMD=$(curl -s -X POST "$SERVER_URL/v1/admin/commands" \
  -H "Content-Type: application/json" \
  -d '{
    "host_id": "'"$HOST_ID"'",
    "command_type": "pkg_install",
    "command_payload": {"name": "htop", "manager": "apt"},
    "timeout_s": 300
  }')

COMMAND_ID=$(echo "$CMD" | jq -r '.id')
echo "Command ID: $COMMAND_ID"

echo "2. Requesting approval..."
APPROVAL=$(curl -s -X POST "$SERVER_URL/v1/admin/commands/$COMMAND_ID/request-approval")
APPROVAL_TOKEN=$(echo "$APPROVAL" | jq -r '.approval_token')
echo "Approval Token: $APPROVAL_TOKEN"

echo "3. Checking pending approvals..."
curl -s "$SERVER_URL/v1/admin/commands/pending-approval" | jq .

echo "4. Waiting 3 seconds (simulate thinking)..."
sleep 3

echo "5. Approving command..."
RESULT=$(curl -s -X POST "$SERVER_URL/v1/admin/commands/approve/$APPROVAL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"approver_id": "test-user", "reason": "Integration test"}')

echo "$RESULT" | jq .

echo "6. Verifying command status..."
curl -s "$SERVER_URL/v1/admin/commands/$COMMAND_ID" | jq '{
  id,
  command_type,
  human_approved,
  approved_by,
  rejected_reason
}'

echo "✓ Test complete"
```

## Debugging Tips

### Enable verbose curl output

```bash
curl -v -X POST "$SERVER_URL/v1/admin/commands/approve/$APPROVAL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"approver_id": "ramonkawa"}'
```

### Check server logs

```bash
ssh root@192.168.0.280
journalctl -u remote-pulse-server -f | grep -i approval
```

### Query database directly

```bash
ssh root@192.168.0.280
sudo -u postgres psql rp -c "
  SELECT id, command_type, human_approved, approved_by, rejected_reason, 
         approval_token IS NOT NULL as has_token,
         approval_requested_at, approval_responded_at
  FROM commands
  WHERE approval_requested_at IS NOT NULL
  ORDER BY issued_at DESC
  LIMIT 10;
"
```

### Test n8n webhook manually

```bash
# Send test payload directly to n8n (bypasses server)
curl -X POST "http://192.168.0.200:5678/webhook/rp-approval" \
  -H "Content-Type: application/json" \
  -d @test-payload.json
```

**test-payload.json**:
```json
{
  "event": "approval_required",
  "command_id": "test-123",
  "command_type": "reboot",
  "command_payload": {"delay_s": 30},
  "host_hostname": "test-host",
  "host_group": "prod",
  "issued_by": "test-user",
  "issued_at": "2026-05-25T14:00:00Z",
  "approval_token": "00000000-0000-0000-0000-000000000001",
  "approval_url_accept": "http://192.168.0.280:8000/v1/admin/commands/approve/00000000-0000-0000-0000-000000000001",
  "approval_url_reject": "http://192.168.0.280:8000/v1/admin/commands/reject/00000000-0000-0000-0000-000000000001",
  "expires_at": "2026-05-25T14:05:00Z"
}
```
